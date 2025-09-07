#!/usr/bin/env python3

from flask import Flask, jsonify, request
import requests
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import logging

load_dotenv()

app = Flask(__name__)

# Configuration
API_KEY = os.getenv('API_KEY', 'sk_live_QzN82iAqzfR09usjYrdYx3lQUkwQWips')
ELECTRICITY_MPAN = os.getenv('ELECTRICITY_MPAN', '1610018835487')
ELECTRICITY_SERIAL = os.getenv('ELECTRICITY_SERIAL', '25L3125760')
GAS_MPRN = os.getenv('GAS_MPRN', '1467503405')
GAS_SERIAL = os.getenv('GAS_SERIAL', 'E6E15302382460')

# Octopus Go Tariff Rates
ELECTRICITY_RATE_PEAK = float(os.getenv('ELECTRICITY_RATE_PEAK', '0.2957'))
ELECTRICITY_RATE_OFF_PEAK = float(os.getenv('ELECTRICITY_RATE_OFF_PEAK', '0.0700'))
GAS_RATE = float(os.getenv('GAS_RATE', '0.0626'))
STANDING_CHARGE_ELECTRICITY = float(os.getenv('STANDING_CHARGE_ELECTRICITY', '0.4734'))
STANDING_CHARGE_GAS = float(os.getenv('STANDING_CHARGE_GAS', '0.2971'))

BASE_URL = "https://api.octopus.energy"
GRAPHQL_URL = "https://api.octopus.energy/v1/graphql"

# Set up logging for production
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class IntelligentOctopusAPI:
    """Enhanced API client with Intelligent Go dispatch support"""
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.auth = (api_key, '')
        self.kraken_token = None
        self.account_number = None
        self.dispatch_periods = []
    
    def get_kraken_token(self):
        """Get Kraken token for GraphQL API access"""
        if self.kraken_token:
            return self.kraken_token
            
        mutation = """
        mutation obtainKrakenToken($input: ObtainJSONWebTokenInput!) {
            obtainKrakenToken(input: $input) {
                token
            }
        }
        """
        
        variables = {
            "input": {
                "APIKey": self.api_key
            }
        }
        
        try:
            response = requests.post(
                GRAPHQL_URL,
                json={"query": mutation, "variables": variables},
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            if "errors" in data:
                logger.error(f"GraphQL token error: {data['errors']}")
                return None
                
            self.kraken_token = data["data"]["obtainKrakenToken"]["token"]
            return self.kraken_token
            
        except Exception as e:
            logger.error(f"Error getting Kraken token: {e}")
            return None
    
    def get_account_number(self):
        """Get account number from GraphQL API"""
        if self.account_number:
            return self.account_number
            
        token = self.get_kraken_token()
        if not token:
            return None
            
        query = """
        query {
            viewer {
                accounts {
                    number
                }
            }
        }
        """
        
        try:
            response = requests.post(
                GRAPHQL_URL,
                json={"query": query},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": token
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            if "errors" in data:
                logger.error(f"GraphQL account error: {data['errors']}")
                return None
                
            accounts = data["data"]["viewer"]["accounts"]
            if accounts:
                self.account_number = accounts[0]["number"]
                return self.account_number
            else:
                logger.error("No accounts found")
                return None
                
        except Exception as e:
            logger.error(f"Error getting account number: {e}")
            return None
    
    def get_recent_dispatches(self):
        """Get recent dispatch periods for smart charging"""
        token = self.get_kraken_token()
        account_number = self.get_account_number()
        
        if not token or not account_number:
            logger.warning("Cannot fetch dispatch data - missing token or account number")
            return []
        
        query = """
        query getDispatches($accountNumber: String!) {
            plannedDispatches(accountNumber: $accountNumber) {
                startDt
                endDt
                delta
                source
            }
            completedDispatches(accountNumber: $accountNumber) {
                startDt
                endDt
                delta
                source
            }
        }
        """
        
        variables = {"accountNumber": account_number}
        
        try:
            response = requests.post(
                GRAPHQL_URL,
                json={"query": query, "variables": variables},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": token
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            if "errors" in data:
                logger.warning(f"GraphQL dispatch error: {data['errors']}")
                return []
            
            dispatches = []
            
            # Process planned dispatches
            planned = data.get("data", {}).get("plannedDispatches", [])
            for dispatch in planned:
                start_dt = datetime.fromisoformat(dispatch["startDt"].replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(dispatch["endDt"].replace("Z", "+00:00"))
                
                dispatches.append({
                    "type": "planned",
                    "start": start_dt,
                    "end": end_dt,
                    "delta": float(dispatch.get("delta", 0)),
                    "source": dispatch.get("source")
                })
            
            # Process completed dispatches (last 24 hours only for performance)
            yesterday = datetime.now() - timedelta(days=1)
            completed = data.get("data", {}).get("completedDispatches", [])
            for dispatch in completed:
                start_dt = datetime.fromisoformat(dispatch["startDt"].replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(dispatch["endDt"].replace("Z", "+00:00"))
                
                # Only include recent completed dispatches
                if start_dt >= yesterday:
                    dispatches.append({
                        "type": "completed",
                        "start": start_dt,
                        "end": end_dt,
                        "delta": float(dispatch.get("delta", 0)),
                        "source": dispatch.get("source")
                    })
            
            self.dispatch_periods = dispatches
            return dispatches
            
        except Exception as e:
            logger.error(f"Error fetching dispatch periods: {e}")
            return []
    
    def is_smart_charging_period(self, timestamp):
        """Check if a timestamp falls within a smart charging dispatch period"""
        for dispatch in self.dispatch_periods:
            if dispatch["start"] <= timestamp <= dispatch["end"]:
                return True, dispatch["type"]
        return False, None

# Global API instance
octopus_api = IntelligentOctopusAPI(API_KEY)

def get_electricity_usage_by_time(mpan, serial, use_mock=False):
    """Get electricity usage split by off-peak, peak, and smart charging periods"""
    
    if use_mock:
        return {
            'off_peak_usage': 6.2,
            'peak_usage': 2.3,
            'smart_charging_usage': 1.8,
            'total_usage': 10.3,
            'smart_charging_sessions': 2
        }
    
    # Get recent dispatch periods
    octopus_api.get_recent_dispatches()
    
    yesterday = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    today = yesterday + timedelta(days=1)
    
    endpoint = f"/v1/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
    url = BASE_URL + endpoint
    params = {
        'period_from': yesterday.isoformat(),
        'period_to': today.isoformat(),
        'page_size': 100
    }
    
    try:
        response = octopus_api.session.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        results = data.get('results', [])
        
        if not results:
            return {
                'off_peak_usage': 0,
                'peak_usage': 0, 
                'smart_charging_usage': 0,
                'total_usage': 0,
                'smart_charging_sessions': 0
            }
        
        off_peak_usage = 0
        peak_usage = 0
        smart_charging_usage = 0
        smart_charging_sessions = set()
        
        for reading in results:
            interval_start = datetime.fromisoformat(reading['interval_start'].replace('Z', '+00:00'))
            consumption = reading['consumption']
            
            hour = interval_start.hour
            minute = interval_start.minute
            
            # Check if this period falls within a smart charging dispatch
            is_smart_charging, dispatch_type = octopus_api.is_smart_charging_period(interval_start)
            
            # Standard off-peak: 23:30-05:30 (Intelligent Octopus Go)
            is_standard_off_peak = (hour == 23 and minute >= 30) or (hour < 5) or (hour == 5 and minute < 30)
            
            if is_smart_charging:
                smart_charging_usage += consumption
                # Count unique charging sessions (group by hour for simplicity)
                smart_charging_sessions.add(f"{interval_start.date()}_{hour}")
            elif is_standard_off_peak:
                off_peak_usage += consumption
            else:
                peak_usage += consumption
        
        return {
            'off_peak_usage': round(off_peak_usage, 2),
            'peak_usage': round(peak_usage, 2),
            'smart_charging_usage': round(smart_charging_usage, 2),
            'total_usage': round(off_peak_usage + peak_usage + smart_charging_usage, 2),
            'smart_charging_sessions': len(smart_charging_sessions)
        }
        
    except Exception as e:
        logger.error(f"Error fetching electricity data: {e}")
        return None

def get_gas_usage(mprn, serial, use_mock=False):
    """Get gas usage for yesterday"""
    
    if use_mock:
        return 12.3
    
    yesterday = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    today = yesterday + timedelta(days=1)
    
    endpoint = f"/v1/gas-meter-points/{mprn}/meters/{serial}/consumption/"
    url = BASE_URL + endpoint
    params = {
        'period_from': yesterday.isoformat(),
        'period_to': today.isoformat(),
        'page_size': 100
    }
    
    try:
        response = octopus_api.session.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        results = data.get('results', [])
        
        if results:
            total_consumption = sum(reading['consumption'] for reading in results)
            return round(total_consumption, 2)
        else:
            return 0
            
    except Exception as e:
        logger.error(f"Error fetching gas data: {e}")
        return None

@app.route('/')
def index():
    return '''
    <html>
    <body style="font-family: Arial; margin: 40px;">
        <h1>TRMNL Energy Plugin - Intelligent Octopus Go</h1>
        <h2>Test Links:</h2>
        <ul>
            <li><a href="/api/energy?mock=true">API Test (Mock Data)</a></li>
            <li><a href="/api/energy">API Test (Live Data)</a></li>
            <li><a href="/trmnl?mock=true">TRMNL Display (Mock)</a></li>
            <li><a href="/trmnl">TRMNL Display (Live)</a></li>
            <li><a href="/health">Health Check</a></li>
        </ul>
        
        <h3>Current Tariff Rates:</h3>
        <p>Off-Peak (23:30-05:30): ''' + str(ELECTRICITY_RATE_OFF_PEAK) + '''p/kWh</p>
        <p>Peak (05:30-23:30): ''' + str(ELECTRICITY_RATE_PEAK) + '''p/kWh</p>
        <p><strong>Smart Charging: ''' + str(ELECTRICITY_RATE_OFF_PEAK) + '''p/kWh (Intelligent dispatch)</strong></p>
        <p>Gas: ''' + str(GAS_RATE) + '''p/kWh</p>
        <p>Standing Charges: Electricity ''' + str(STANDING_CHARGE_ELECTRICITY) + '''p/day, Gas ''' + str(STANDING_CHARGE_GAS) + '''p/day</p>
    </body>
    </html>
    '''

@app.route('/api/energy')
def energy_data():
    use_mock = request.args.get('mock', 'false').lower() == 'true'
    
    yesterday = datetime.now() - timedelta(days=1)
    date_str = yesterday.strftime("%d %b %Y")
    
    electricity_data = get_electricity_usage_by_time(ELECTRICITY_MPAN, ELECTRICITY_SERIAL, use_mock)
    gas_usage = get_gas_usage(GAS_MPRN, GAS_SERIAL, use_mock)
    
    if electricity_data is None or gas_usage is None:
        return jsonify({
            "date": date_str,
            "error": "Failed to fetch data",
            "timestamp": datetime.now().isoformat()
        })
    
    # Calculate costs
    off_peak_cost = round(electricity_data['off_peak_usage'] * ELECTRICITY_RATE_OFF_PEAK, 2)
    peak_cost = round(electricity_data['peak_usage'] * ELECTRICITY_RATE_PEAK, 2)
    smart_charging_cost = round(electricity_data['smart_charging_usage'] * ELECTRICITY_RATE_OFF_PEAK, 2)
    total_electricity_cost = round(off_peak_cost + peak_cost + smart_charging_cost + STANDING_CHARGE_ELECTRICITY, 2)
    
    gas_cost = round(gas_usage * GAS_RATE + STANDING_CHARGE_GAS, 2)
    
    total_cost = round(total_electricity_cost + gas_cost, 2)
    
    # Calculate potential savings from smart charging
    smart_charging_savings = round(electricity_data['smart_charging_usage'] * (ELECTRICITY_RATE_PEAK - ELECTRICITY_RATE_OFF_PEAK), 2)
    
    return jsonify({
        "date": date_str,
        "electricity": {
            "off_peak": {
                "usage": electricity_data['off_peak_usage'],
                "rate": ELECTRICITY_RATE_OFF_PEAK,
                "cost": off_peak_cost,
                "period": "23:30-05:30"
            },
            "peak": {
                "usage": electricity_data['peak_usage'],
                "rate": ELECTRICITY_RATE_PEAK,
                "cost": peak_cost,
                "period": "05:30-23:30"
            },
            "smart_charging": {
                "usage": electricity_data['smart_charging_usage'],
                "rate": ELECTRICITY_RATE_OFF_PEAK,
                "cost": smart_charging_cost,
                "sessions": electricity_data['smart_charging_sessions'],
                "savings": smart_charging_savings,
                "period": "Intelligent dispatch"
            },
            "total_usage": electricity_data['total_usage'],
            "total_cost": total_electricity_cost,
            "standing_charge": STANDING_CHARGE_ELECTRICITY,
            "unit": "kWh"
        },
        "gas": {
            "usage": gas_usage,
            "rate": GAS_RATE,
            "cost": gas_cost,
            "standing_charge": STANDING_CHARGE_GAS,
            "unit": "m³"
        },
        "total_cost": total_cost,
        "currency": "GBP",
        "timestamp": datetime.now().isoformat(),
        "mock_data": use_mock,
        "intelligent_features": {
            "dispatch_periods_found": len(octopus_api.dispatch_periods),
            "smart_charging_active": electricity_data['smart_charging_usage'] > 0,
            "total_savings": smart_charging_savings
        }
    })

@app.route('/trmnl')
def trmnl_display():
    use_mock = request.args.get('mock', 'false')
    api_url = '/api/energy?mock=' + use_mock if use_mock == 'true' else '/api/energy'
    
    html_template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Energy Usage - Intelligent Octopus Go</title>
        <style>
            body { 
                font-family: monospace;
                margin: 15px; 
                background: white;
                color: black;
                font-size: 16px;
            }
            .header { 
                font-size: 24px; 
                font-weight: bold; 
                margin-bottom: 15px; 
                text-align: center;
                border-bottom: 2px solid black;
                padding-bottom: 8px;
            }
            .date {
                text-align: center; 
                margin-bottom: 20px; 
                font-size: 14px;
            }
            .section { 
                margin: 15px 0; 
                border: 1px solid #ddd;
                padding: 10px;
                border-radius: 5px;
            }
            .section-title {
                font-weight: bold;
                margin-bottom: 8px;
                font-size: 18px;
            }
            .usage-row { 
                display: flex;
                justify-content: space-between;
                margin: 5px 0;
                font-size: 14px;
            }
            .smart-charging-row {
                display: flex;
                justify-content: space-between;
                margin: 5px 0;
                font-size: 14px;
                background-color: #e8f5e8;
                padding: 3px;
                border-radius: 3px;
            }
            .total-row {
                display: flex;
                justify-content: space-between;
                margin: 8px 0;
                font-weight: bold;
                border-top: 1px solid #ccc;
                padding-top: 5px;
            }
            .grand-total { 
                margin-top: 20px; 
                font-size: 20px; 
                font-weight: bold; 
                text-align: center;
                border-top: 2px solid black;
                padding-top: 15px;
            }
            .savings-highlight {
                background-color: #d4edda;
                padding: 8px;
                border-radius: 5px;
                margin: 10px 0;
                text-align: center;
                font-weight: bold;
                color: #155724;
            }
            .footer {
                text-align: center; 
                font-size: 11px; 
                margin-top: 15px;
                color: #666;
            }
        </style>
    </head>
    <body>
        <div class="header">Energy Usage</div>
        <div id="content">Loading...</div>
        
        <script>
            fetch('API_URL_PLACEHOLDER')
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        document.getElementById('content').innerHTML = '<div style="text-align: center; color: red;">Error: ' + data.error + '</div>';
                        return;
                    }
                    
                    const elec = data.electricity;
                    const gas = data.gas;
                    const intelligent = data.intelligent_features;
                    
                    let content = '<div class="date">' + data.date + '</div>';
                    
                    // Electricity section
                    content += '<div class="section">' +
                        '<div class="section-title">⚡ Electricity</div>' +
                        '<div class="usage-row"><span>Off-Peak (' + elec.off_peak.period + '):</span><span>' + elec.off_peak.usage + ' kWh (£' + elec.off_peak.cost.toFixed(2) + ')</span></div>' +
                        '<div class="usage-row"><span>Peak (' + elec.peak.period + '):</span><span>' + elec.peak.usage + ' kWh (£' + elec.peak.cost.toFixed(2) + ')</span></div>';
                    
                    // Smart charging row - highlighted if active
                    if (elec.smart_charging.usage > 0) {
                        content += '<div class="smart-charging-row"><span>🚗 Smart Charging (' + elec.smart_charging.sessions + ' sessions):</span><span>' + elec.smart_charging.usage + ' kWh (£' + elec.smart_charging.cost.toFixed(2) + ')</span></div>';
                    } else {
                        content += '<div class="usage-row"><span>🚗 Smart Charging:</span><span>0 kWh (£0.00)</span></div>';
                    }
                    
                    content += '<div class="usage-row"><span>Standing Charge:</span><span>£' + elec.standing_charge.toFixed(2) + '</span></div>' +
                        '<div class="total-row"><span>Total:</span><span>' + elec.total_usage + ' kWh (£' + elec.total_cost.toFixed(2) + ')</span></div>' +
                        '</div>';
                    
                    // Show savings if smart charging was used
                    if (elec.smart_charging.savings > 0) {
                        content += '<div class="savings-highlight">Smart charging saved £' + elec.smart_charging.savings.toFixed(2) + ' today!</div>';
                    }
                    
                    // Gas section
                    content += '<div class="section">' +
                        '<div class="section-title">🔥 Gas</div>' +
                        '<div class="usage-row"><span>Usage:</span><span>' + gas.usage + ' m³</span></div>' +
                        '<div class="usage-row"><span>Unit Cost:</span><span>£' + (gas.cost - gas.standing_charge).toFixed(2) + '</span></div>' +
                        '<div class="usage-row"><span>Standing Charge:</span><span>£' + gas.standing_charge.toFixed(2) + '</span></div>' +
                        '<div class="total-row"><span>Total:</span><span>£' + gas.cost.toFixed(2) + '</span></div>' +
                        '</div>';
                    
                    // Grand total
                    content += '<div class="grand-total">Daily Total: £' + data.total_cost.toFixed(2) + '</div>';
                    
                    // Footer with intelligent features info
                    let footerText = data.mock_data ? 'Mock Data' : 'Live Data';
                    if (intelligent.dispatch_periods_found > 0) {
                        footerText += ' • ' + intelligent.dispatch_periods_found + ' dispatches found';
                    }
                    content += '<div class="footer">' + footerText + '</div>';
                    
                    document.getElementById('content').innerHTML = content;
                })
                .catch(error => {
                    document.getElementById('content').innerHTML = '<div style="text-align: center; color: red;">Error loading data</div>';
                });
        </script>
    </body>
    </html>
    '''
    
    return html_template.replace('API_URL_PLACEHOLDER', api_url)

@app.route('/health')
def health_check():
    return jsonify({
        "status": "ok", 
        "timestamp": datetime.now().isoformat(),
        "intelligent_octopus": True,
        "api_features": ["dispatch_tracking", "smart_charging_detection"]
    })

if __name__ == '__main__':
    print("Starting TRMNL Octopus Energy Plugin server with Intelligent Go support")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

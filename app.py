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

# Set up logging
logging.basicConfig(level=logging.INFO)
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
        <h1>TRMNL Energy Plugin Test - Intelligent Octopus Go</h1>
        <h2>Test Links:</h2>
        <ul>
            <li><a href="/api/energy?mock=true">API Test (Mock Data)</a></li>
            <li><a href="/api/energy">API Test (Live Data)</a></li>
            <li><a href="/trmnl?mock=true">TRMNL Display (Mock)</a></li>
            <li><a href="/trmnl">TRMNL Display (Live)</a></li>
            <li><a href="/dispatches">View Recent Dispatches</a></li>
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

@app.route('/dispatches')
def dispatches():
    """Display recent dispatch information"""
    dispatches = octopus_api.get_recent_dispatches()
    
    html = '''
    <html>
    <body style="font-family: Arial; margin: 40px;">
        <h1>Recent Intelligent Octopus Dispatches</h1>
        <a href="/">&larr; Back to main</a>
    '''
    
    if dispatches:
        html += '<h2>Planned Dispatches:</h2><ul>'
        for dispatch in [d for d in dispatches if d['type'] == 'planned']:
            html += f'<li>{dispatch["start"].strftime("%Y-%m-%d %H:%M")} to {dispatch["end"].strftime("%H:%M")} - {dispatch["delta"]:.1f} kWh</li>'
        
        html += '</ul><h2>Recent Completed Dispatches:</h2><ul>'
        for dispatch in [d for d in dispatches if d['type'] == 'completed']:
            html += f'<li>{dispatch["start"].strftime("%Y-%m-%d %H:%M")} to {dispatch["end"].strftime("%H:%M")} - {dispatch["delta"]:.1f} kWh</li>'
        html += '</ul>'
    else:
        html += '<p>No dispatch data available.</p>'
    
    html += '</body></html>'
    return html

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
    """TRMNL endpoint that returns populated HTML"""
    use_mock = request.args.get('mock', 'false').lower() == 'true'
    
    yesterday = datetime.now() - timedelta(days=1)
    date_str = yesterday.strftime("%d %b %Y")
    
    electricity_data = get_electricity_usage_by_time(ELECTRICITY_MPAN, ELECTRICITY_SERIAL, use_mock)
    gas_usage = get_gas_usage(GAS_MPRN, GAS_SERIAL, use_mock)
    
    if electricity_data is None or gas_usage is None:
        return f'''
        <div class="layout layout--col">
            <div class="text--center">
                <div class="content">
                    <span class="title">❌ Error</span>
                    <span class="value">Failed to fetch data</span>
                </div>
            </div>
        </div>
        <div class="title_bar">
            <span class="title">Energy Usage - {date_str}</span>
        </div>
        '''
    
    # Calculate costs
    off_peak_cost = round(electricity_data['off_peak_usage'] * ELECTRICITY_RATE_OFF_PEAK, 2)
    peak_cost = round(electricity_data['peak_usage'] * ELECTRICITY_RATE_PEAK, 2)
    smart_charging_cost = round(electricity_data['smart_charging_usage'] * ELECTRICITY_RATE_OFF_PEAK, 2)
    total_electricity_cost = round(off_peak_cost + peak_cost + smart_charging_cost + STANDING_CHARGE_ELECTRICITY, 2)
    
    gas_cost = round(gas_usage * GAS_RATE + STANDING_CHARGE_GAS, 2)
    total_cost = round(total_electricity_cost + gas_cost, 2)
    
    # Convert gas to kWh
    gas_usage_kwh = gas_usage * 11.2
    
    # Calculate smart charging savings
    smart_charging_savings = round(electricity_data['smart_charging_usage'] * (ELECTRICITY_RATE_PEAK - ELECTRICITY_RATE_OFF_PEAK), 2)
    
    # Add savings alert if smart charging saved money
    savings_alert = ""
    if smart_charging_savings > 0:
        savings_alert = f'''
        <div class="text--center" style="background: #e8f5e8; border: 1px solid #4caf50; border-radius: 4px; padding: 8px; margin-bottom: 10px;">
            <span class="label" style="color: #2e7d32; font-weight: bold;">🚗 Smart Charging Saved £{smart_charging_savings:.2f}</span>
        </div>
        '''
    
    # Add car emoji if smart charging is active
    car_emoji = "🚗" if electricity_data['smart_charging_usage'] > 0 else ""
    
    # Add mock data indicator
    mock_indicator = "🧪" if use_mock else ""
    
    # Return populated HTML directly
    return f'''
    <div class="layout layout--col">
      {savings_alert}
      <div class="columns text--center">
        <div class="column">
          <div class="content">
            <span class="title">⚡ ELECTRICITY</span>
            <span class="value">{electricity_data['total_usage']} kWh</span>
            <span class="value">£{total_electricity_cost:.2f}</span>
            <span class="label">Off-Peak: {electricity_data['off_peak_usage']} kWh</span>
            <span class="label">Peak: {electricity_data['peak_usage']} kWh</span>
            <span class="label">🚗 Smart: {electricity_data['smart_charging_usage']} kWh</span>
            <span class="label">Standing: £{STANDING_CHARGE_ELECTRICITY:.2f}</span>
          </div>
        </div>
        
        <div class="column">
          <div class="content">
            <span class="title">🔥 GAS</span>
            <span class="value">{gas_usage_kwh:.1f} kWh</span>
            <span class="value">£{gas_cost:.2f}</span>
            <span class="label">Usage: {gas_usage} m³</span>
            <span class="label">Standing: £{STANDING_CHARGE_GAS:.2f}</span>
          </div>
        </div>
      </div>

      <div>&nbsp;</div>
      
      <div class="columns text--center">
        <div class="column">
          <div class="content">
            <span class="title">💷 DAILY TOTAL</span>
            <span class="value">£{total_cost:.2f}</span>
          </div>
        </div>
        
        <div class="column">
          <div class="content">
            <span class="title">🚗 EV SESSIONS</span>
            <span class="value">{electricity_data['smart_charging_sessions']}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="title_bar">
      <span class="title">Energy Usage - {date_str} {car_emoji} {mock_indicator}</span>
    </div>
    '''

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

#!/usr/bin/env python3

from flask import Flask, jsonify, request
import requests
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import logging

load_dotenv()

app = Flask(__name__)

# Configuration - Environment variables only, no defaults
API_KEY = os.getenv('API_KEY')
ELECTRICITY_MPAN = os.getenv('ELECTRICITY_MPAN')
ELECTRICITY_SERIAL = os.getenv('ELECTRICITY_SERIAL')
GAS_MPRN = os.getenv('GAS_MPRN')
GAS_SERIAL = os.getenv('GAS_SERIAL')

# Validate required environment variables
required_vars = {
    'API_KEY': API_KEY,
    'ELECTRICITY_MPAN': ELECTRICITY_MPAN,
    'ELECTRICITY_SERIAL': ELECTRICITY_SERIAL,
    'GAS_MPRN': GAS_MPRN,
    'GAS_SERIAL': GAS_SERIAL
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Octopus Go Tariff Rates
ELECTRICITY_RATE_PEAK = float(os.getenv('ELECTRICITY_RATE_PEAK', '0.2957'))
ELECTRICITY_RATE_OFF_PEAK = float(os.getenv('ELECTRICITY_RATE_OFF_PEAK', '0.0700'))
GAS_RATE = float(os.getenv('GAS_RATE', '0.0626'))
STANDING_CHARGE_ELECTRICITY = float(os.getenv('STANDING_CHARGE_ELECTRICITY', '0.4734'))
STANDING_CHARGE_GAS = float(os.getenv('STANDING_CHARGE_GAS', '0.2971'))

BASE_URL = "https://api.octopus.energy"

# Set up logging for production
logging.basicConfig(level=logging.INFO)  # Changed to INFO to see gas calculation logs
logger = logging.getLogger(__name__)

def get_electricity_usage_by_time(mpan, serial, use_mock=False):
    """Get electricity usage split by off-peak and peak periods"""
    
    if use_mock:
        return {
            'off_peak_usage': 6.2,
            'peak_usage': 2.3,
            'total_usage': 8.5
        }
    
    # Calculate yesterday's date range PRECISELY - matching gas function
    now = datetime.now()
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end = yesterday_start.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    endpoint = f"/v1/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
    url = BASE_URL + endpoint
    params = {
        'period_from': yesterday_start.isoformat(),
        'period_to': yesterday_end.isoformat(),  # Changed: precise end time
        'page_size': 1000  # Increased from 100
    }
    
    try:
        session = requests.Session()
        session.auth = (API_KEY, '')
        
        all_results = []
        current_url = url
        
        # Handle pagination properly
        while current_url:
            response = session.get(current_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            results = data.get('results', [])
            
            logger.info(f"Electricity API page: {len(results)} readings")
            all_results.extend(results)
            
            # Check for next page
            current_url = data.get('next')
            params = None  # Clear params for subsequent requests
        
        logger.info(f"Total electricity readings retrieved: {len(all_results)}")
        
        if not all_results:
            return {
                'off_peak_usage': 0,
                'peak_usage': 0, 
                'total_usage': 0
            }
        
        # Filter results to ensure we only get yesterday's data
        yesterday_results = []
        for reading in all_results:
            reading_time = datetime.fromisoformat(reading['interval_start'].replace('Z', '+00:00'))
            # Convert to local time if needed and check if it's yesterday
            if yesterday_start <= reading_time.replace(tzinfo=None) <= yesterday_end:
                yesterday_results.append(reading)
        
        logger.info(f"Filtered to yesterday only: {len(yesterday_results)} readings")
        
        off_peak_usage = 0
        peak_usage = 0
        
        for reading in yesterday_results:
            interval_start = datetime.fromisoformat(reading['interval_start'].replace('Z', '+00:00'))
            consumption = reading['consumption']
            
            hour = interval_start.hour
            minute = interval_start.minute
            
            # Standard off-peak: 23:30-05:30 (Octopus Go)
            is_off_peak = (hour == 23 and minute >= 30) or (hour < 5) or (hour == 5 and minute < 30)
            
            if is_off_peak:
                off_peak_usage += consumption
            else:
                peak_usage += consumption
        
        total_usage = off_peak_usage + peak_usage
        
        return {
            'off_peak_usage': round(off_peak_usage, 2),
            'peak_usage': round(peak_usage, 2),
            'total_usage': round(total_usage, 2)
        }
        
    except Exception as e:
        logger.error(f"Error fetching electricity data: {e}")
        return None


def get_gas_usage(mprn, serial, use_mock=False):
    """Get gas usage for yesterday ONLY, with precise date range"""
    
    if use_mock:
        return 44.5
    
    # Gas conversion factor: m³ to kWh (this is correct)
    GAS_M3_TO_KWH = 11.1868
    
    # Calculate yesterday's date range PRECISELY
    now = datetime.now()
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end = yesterday_start.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Alternative: Use today's start as yesterday's end
    # today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    endpoint = f"/v1/gas-meter-points/{mprn}/meters/{serial}/consumption/"
    url = BASE_URL + endpoint
    params = {
        'period_from': yesterday_start.isoformat(),
        'period_to': yesterday_end.isoformat(),  # Changed: precise end time
        'page_size': 1000
    }
    
    try:
        session = requests.Session()
        session.auth = (API_KEY, '')
        
        all_results = []
        current_url = url
        
        # Handle pagination properly
        while current_url:
            response = session.get(current_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            results = data.get('results', [])
            
            logger.info(f"Gas API page: {len(results)} readings")
            all_results.extend(results)
            
            # Check for next page
            current_url = data.get('next')
            params = None  # Clear params for subsequent requests
        
        logger.info(f"Total gas readings retrieved: {len(all_results)}")
        logger.info(f"Date range: {yesterday_start.isoformat()} to {yesterday_end.isoformat()}")
        
        if all_results:
            # Filter results to ensure we only get yesterday's data
            yesterday_results = []
            for reading in all_results:
                reading_time = datetime.fromisoformat(reading['interval_start'].replace('Z', '+00:00'))
                # Convert to local time if needed and check if it's yesterday
                if yesterday_start <= reading_time.replace(tzinfo=None) <= yesterday_end:
                    yesterday_results.append(reading)
            
            logger.info(f"Filtered to yesterday only: {len(yesterday_results)} readings")
            
            # Debug: Log a few sample readings
            for i, reading in enumerate(yesterday_results[:3]):
                logger.info(f"Gas reading {i+1}: {reading['consumption']} m³ at {reading['interval_start']}")
            
            # Sum all readings in m³ for yesterday only
            total_consumption_m3 = sum(reading['consumption'] for reading in yesterday_results)
            logger.info(f"Total gas consumption (yesterday only): {total_consumption_m3:.3f} m³")
            
            # Convert to kWh using the conversion factor
            total_consumption_kwh = total_consumption_m3 * GAS_M3_TO_KWH
            logger.info(f"Gas consumption in kWh: {total_consumption_kwh:.2f} kWh")
            
            # If yesterday had no consumption, try last 7 days for daily average
            if total_consumption_m3 == 0:
                logger.info("No gas usage yesterday, trying last 7 days...")
                week_ago = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
                
                # Fetch week data with pagination
                week_params = {
                    'period_from': week_ago.isoformat(),
                    'period_to': yesterday_end.isoformat(),  # End at yesterday, not today
                    'page_size': 1000
                }
                
                week_results = []
                week_url = url
                
                while week_url:
                    response_week = session.get(week_url, params=week_params, timeout=10)
                    response_week.raise_for_status()
                    data_week = response_week.json()
                    results_week = data_week.get('results', [])
                    week_results.extend(results_week)
                    
                    week_url = data_week.get('next')
                    week_params = None
                
                if week_results:
                    total_week_m3 = sum(reading['consumption'] for reading in week_results)
                    total_week_kwh = total_week_m3 * GAS_M3_TO_KWH
                    daily_average_kwh = total_week_kwh / 7
                    logger.info(f"7-day average gas usage: {daily_average_kwh:.2f} kWh/day")
                    return round(daily_average_kwh, 2)
            
            # Return the converted kWh value for yesterday only
            return round(total_consumption_kwh, 2) if total_consumption_kwh > 0 else 0
        else:
            logger.warning("No gas readings found for yesterday")
            return 0
            
    except Exception as e:
        logger.error(f"Error fetching gas data: {e}")
        return None


@app.route('/')
def index():
    return '''
    <html>
    <body style="font-family: Arial; margin: 40px;">
        <h1>TRMNL Energy Plugin</h1>
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
    
    # Calculate costs - ensure 2 decimal places with proper rounding
    off_peak_cost = round(electricity_data['off_peak_usage'] * ELECTRICITY_RATE_OFF_PEAK, 2)
    peak_cost = round(electricity_data['peak_usage'] * ELECTRICITY_RATE_PEAK, 2)
    total_electricity_cost = round(off_peak_cost + peak_cost + STANDING_CHARGE_ELECTRICITY, 2)
    
    gas_cost = round(gas_usage * GAS_RATE + STANDING_CHARGE_GAS, 2)
    
    total_cost = round(total_electricity_cost + gas_cost, 2)
    
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
            "unit": "kWh"  # Changed from m³ to kWh since we're returning converted values
        },
        "total_cost": total_cost,
        "currency": "GBP",
        "timestamp": datetime.now().isoformat(),
        "mock_data": use_mock
    })

@app.route('/trmnl')
def trmnl_display():
    """TRMNL JSON endpoint - returns flat JSON data for TRMNL markup templates"""
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
    
    # Calculate costs - ensure 2 decimal places with proper rounding
    off_peak_cost = round(electricity_data['off_peak_usage'] * ELECTRICITY_RATE_OFF_PEAK, 2)
    peak_cost = round(electricity_data['peak_usage'] * ELECTRICITY_RATE_PEAK, 2)
    total_electricity_cost = round(off_peak_cost + peak_cost + STANDING_CHARGE_ELECTRICITY, 2)
    
    # Gas calculations
    gas_usage_only_cost = round(gas_usage * GAS_RATE, 2)  # Just the usage cost, no standing charge
    gas_cost = round(gas_usage_only_cost + STANDING_CHARGE_GAS, 2)  # Total gas cost
    total_cost = round(total_electricity_cost + gas_cost, 2)
    
    # Return flat JSON structure for TRMNL - ALL CURRENCY VALUES WITH 2 DECIMAL PLACES
    return jsonify({
        "date": date_str,
        "electricity_off_peak_usage": electricity_data['off_peak_usage'],
        "electricity_off_peak_cost": f"{off_peak_cost:.2f}",
        "electricity_peak_usage": electricity_data['peak_usage'], 
        "electricity_peak_cost": f"{peak_cost:.2f}",
        "electricity_total_usage": electricity_data['total_usage'],
        "electricity_total_cost": f"{total_electricity_cost:.2f}",
        "electricity_standing_charge": f"{STANDING_CHARGE_ELECTRICITY:.2f}",
        "gas_usage": gas_usage,
        "gas_usage_only_cost": f"{gas_usage_only_cost:.2f}",  # NEW: Gas usage cost without standing charge
        "gas_cost": f"{gas_cost:.2f}",
        "gas_standing_charge": f"{STANDING_CHARGE_GAS:.2f}",
        "total_cost": f"{total_cost:.2f}",
        "timestamp": datetime.now().isoformat(),
        "mock_data": use_mock
    })

@app.route('/trmnl-html')
def trmnl_html():
    """TRMNL HTML endpoint - returns complete HTML page"""
    use_mock = request.args.get('mock', 'false')
    api_url = '/api/energy?mock=' + use_mock if use_mock == 'true' else '/api/energy'
    
    html_template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Energy Usage</title>
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
                    
                    let content = '<div class="date">' + data.date + '</div>';
                    
                    // Electricity section
                    content += '<div class="section">' +
                        '<div class="section-title">ELECTRICITY</div>' +
                        '<div class="usage-row"><span>Off-Peak: ' + elec.off_peak.usage + ' kWh</span><span>£' + elec.off_peak.cost.toFixed(2) + '</span></div>' +
                        '<div class="usage-row"><span>Peak: ' + elec.peak.usage + ' kWh</span><span>£' + elec.peak.cost.toFixed(2) + '</span></div>' +
                        '<div class="usage-row"><span>Standing: £' + elec.standing_charge.toFixed(2) + '</span><span>£' + elec.standing_charge.toFixed(2) + '</span></div>' +
                        '<div class="total-row"><span>' + elec.total_usage + ' kWh</span><span>£' + elec.total_cost.toFixed(2) + '</span></div>' +
                        '</div>';
                    
                    // Gas section - now showing kWh instead of m³ with proper decimal formatting
                    const gasUsageCost = (gas.usage * gas.rate).toFixed(2);
                    const gasDisplayUsage = gas.usage > 0 ? gas.usage.toFixed(1) + ' kWh' : '0.0 kWh';
                    const gasStandingCharge = parseFloat(gas.standing_charge).toFixed(2);
                    
                    content += '<div class="section">' +
                        '<div class="section-title">GAS</div>' +
                        '<div class="usage-row"><span>Usage: ' + gasDisplayUsage + '</span><span>£' + gasUsageCost + '</span></div>' +
                        '<div class="usage-row"><span>Standing: £' + gasStandingCharge + '</span><span>£' + gasStandingCharge + '</span></div>' +
                        '<div class="total-row"><span>' + gasDisplayUsage + '</span><span>£' + parseFloat(gas.cost).toFixed(2) + '</span></div>' +
                        '</div>';
                    
                    // Grand total - ensuring exactly 2 decimal places
                    content += '<div class="grand-total">DAILY TOTAL<br>£' + parseFloat(data.total_cost).toFixed(2) + '</div>';
                    
                    // Footer 
                    let footerText = data.mock_data ? 'Mock Data' : 'Synced: about 8 hours ago';
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
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    print("Starting TRMNL Octopus Energy Plugin server")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

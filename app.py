#!/usr/bin/env python3
"""
Octopus Energy Usage Tracker for TRMNL
Fetches electricity and gas consumption data and returns JSON for TRMNL polling
"""

import os
import requests
import json
from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration - reads from environment variables
API_KEY = os.getenv('OCTOPUS_API_KEY', 'sk_live_your_api_key_here')
ELECTRICITY_MPAN = os.getenv('ELECTRICITY_MPAN', '1610018835487')
ELECTRICITY_SERIAL = os.getenv('ELECTRICITY_SERIAL', '25L3125760')
GAS_MPRN = os.getenv('GAS_MPRN', '1467503405')
GAS_SERIAL = os.getenv('GAS_SERIAL', 'E6E15302382460')

# Constants
GAS_CONVERSION_FACTOR = 11.1  # kWh per m³ (UK standard)
ELECTRICITY_STANDING_CHARGE = 0.4702  # £/day
GAS_STANDING_CHARGE = 0.3058  # £/day

# Rate configuration for Octopus Go
RATES = {
    'off_peak': 0.075,  # 7.5p/kWh (00:30-04:30)
    'peak': 0.2494,     # 24.94p/kWh (other times)
    'smart_charging': 0.075  # 7.5p/kWh (intelligent dispatch)
}

def get_yesterday_date():
    """Get yesterday's date in YYYY-MM-DD format"""
    yesterday = datetime.now() - timedelta(days=1)
    return yesterday.strftime('%Y-%m-%d')

def get_energy_data():
    """Get all energy data and process it - unified function for all routes"""
    date = get_yesterday_date()
    
    # Initialize with defaults
    result = {
        'date': date,
        'electricity': {
            'total_usage': 0,
            'off_peak_usage': 0,
            'peak_usage': 0,
            'smart_charging_usage': 0,
            'total_cost': 0,
            'standing_charge': ELECTRICITY_STANDING_CHARGE
        },
        'gas': {
            'usage_m3': 0,
            'usage_kwh': 0,
            'cost': 0,
            'standing_charge': GAS_STANDING_CHARGE
        },
        'smart_charging': {
            'sessions': 0,
            'savings': 0
        },
        'totals': {
            'daily_cost': ELECTRICITY_STANDING_CHARGE + GAS_STANDING_CHARGE
        }
    }
    
    # Fetch electricity data
    try:
        elec_url = f"https://api.octopus.energy/v1/electricity-meter-points/{ELECTRICITY_MPAN}/meters/{ELECTRICITY_SERIAL}/consumption/"
        elec_params = {
            'period_from': f"{date}T00:00:00Z",
            'period_to': f"{date}T23:59:59Z",
            'page_size': 200
        }
        elec_response = requests.get(elec_url, params=elec_params, auth=(API_KEY, ''), timeout=30)
        
        if elec_response.status_code == 200:
            elec_data = elec_response.json()
            
            total_usage = 0
            off_peak_usage = 0
            peak_usage = 0
            total_cost = 0
            
            for reading in elec_data.get('results', []):
                consumption = reading.get('consumption', 0)
                interval_start = reading.get('interval_start', '')
                
                # Parse the time to determine rate period
                try:
                    dt = datetime.fromisoformat(interval_start.replace('Z', '+00:00'))
                    hour = dt.hour
                    minute = dt.minute
                    
                    # Off-peak hours: 00:30 to 04:30
                    is_off_peak = (hour == 0 and minute >= 30) or (1 <= hour <= 3) or (hour == 4 and minute < 30)
                    
                    total_usage += consumption
                    
                    if is_off_peak:
                        off_peak_usage += consumption
                        total_cost += consumption * RATES['off_peak']
                    else:
                        peak_usage += consumption
                        total_cost += consumption * RATES['peak']
                        
                except Exception as e:
                    logger.warning(f"Error parsing datetime {interval_start}: {e}")
                    # Default to peak rate if parsing fails
                    total_usage += consumption
                    peak_usage += consumption
                    total_cost += consumption * RATES['peak']
            
            result['electricity'] = {
                'total_usage': round(total_usage, 2),
                'off_peak_usage': round(off_peak_usage, 2),
                'peak_usage': round(peak_usage, 2),
                'smart_charging_usage': 0,  # Will be enhanced later
                'total_cost': round(total_cost, 2),
                'standing_charge': ELECTRICITY_STANDING_CHARGE
            }
        else:
            logger.error(f"Electricity API error: {elec_response.status_code} - {elec_response.text}")
    
    except Exception as e:
        logger.error(f"Failed to fetch electricity data: {e}")
    
    # Fetch gas data
    try:
        gas_url = f"https://api.octopus.energy/v1/gas-meter-points/{GAS_MPRN}/meters/{GAS_SERIAL}/consumption/"
        gas_params = {
            'period_from': f"{date}T00:00:00Z",
            'period_to': f"{date}T23:59:59Z",
            'page_size': 200
        }
        gas_response = requests.get(gas_url, params=gas_params, auth=(API_KEY, ''), timeout=30)
        
        if gas_response.status_code == 200:
            gas_data = gas_response.json()
            
            total_usage_m3 = 0
            total_cost = 0
            
            for reading in gas_data.get('results', []):
                consumption = reading.get('consumption', 0)
                total_usage_m3 += consumption
                # Calculate cost using current gas rate (approximate)
                total_cost += consumption * 0.0626  # Current gas rate per m³
            
            # Convert m³ to kWh
            total_usage_kwh = total_usage_m3 * GAS_CONVERSION_FACTOR
            
            result['gas'] = {
                'usage_m3': round(total_usage_m3, 3),
                'usage_kwh': round(total_usage_kwh, 2),
                'cost': round(total_cost, 2),
                'standing_charge': GAS_STANDING_CHARGE
            }
        else:
            logger.error(f"Gas API error: {gas_response.status_code} - {gas_response.text}")
    
    except Exception as e:
        logger.error(f"Failed to fetch gas data: {e}")
    
    # Calculate total daily cost
    result['totals']['daily_cost'] = round(
        result['electricity']['total_cost'] + 
        result['gas']['cost'] + 
        ELECTRICITY_STANDING_CHARGE + 
        GAS_STANDING_CHARGE, 2
    )
    
    return result

@app.route('/')
def index():
    """Main route - shows energy usage data in HTML format"""
    data = get_energy_data()
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Energy Usage - {data['date']}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            .section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 8px; }}
            .title {{ font-size: 1.2em; font-weight: bold; margin-bottom: 10px; }}
            .value {{ font-size: 1.1em; margin: 5px 0; }}
            .total {{ background: #f5f5f5; }}
        </style>
    </head>
    <body>
        <h1>Energy Usage - {data['date']}</h1>
        
        <div class="section">
            <div class="title">⚡ Electricity</div>
            <div class="value">Total: {data['electricity']['total_usage']} kWh (£{data['electricity']['total_cost']:.2f})</div>
            <div class="value">Off-peak: {data['electricity']['off_peak_usage']} kWh</div>
            <div class="value">Peak: {data['electricity']['peak_usage']} kWh</div>
            <div class="value">Smart charging: {data['electricity']['smart_charging_usage']} kWh</div>
            <div class="value">Standing charge: £{data['electricity']['standing_charge']:.2f}</div>
        </div>
        
        <div class="section">
            <div class="title">🔥 Gas</div>
            <div class="value">Usage: {data['gas']['usage_kwh']} kWh ({data['gas']['usage_m3']} m³)</div>
            <div class="value">Cost: £{data['gas']['cost']:.2f}</div>
            <div class="value">Standing charge: £{data['gas']['standing_charge']:.2f}</div>
        </div>
        
        <div class="section total">
            <div class="title">💷 Daily Total</div>
            <div class="value">Total cost: £{data['totals']['daily_cost']:.2f}</div>
            <div class="value">EV sessions: {data['smart_charging']['sessions']}</div>
        </div>
        
        <p><small>Live Data</small></p>
    </body>
    </html>
    """

@app.route('/trmnl')
def trmnl():
    """TRMNL endpoint - returns JSON data for polling mode"""
    data = get_energy_data()
    
    # Return JSON with flat variable names that match the template
    return jsonify({
        'date': data['date'],
        'electricity_total_usage': data['electricity']['total_usage'],
        'electricity_off_peak_usage': data['electricity']['off_peak_usage'],
        'electricity_peak_usage': data['electricity']['peak_usage'],
        'electricity_total_cost': data['electricity']['total_cost'],
        'electricity_standing_charge': data['electricity']['standing_charge'],
        'gas_usage_kwh': data['gas']['usage_kwh'],
        'gas_cost': data['gas']['cost'],
        'gas_standing_charge': data['gas']['standing_charge'],
        'smart_charging_usage': data['electricity']['smart_charging_usage'],
        'smart_charging_sessions': data['smart_charging']['sessions'],
        'smart_charging_savings': data['smart_charging']['savings'],
        'total_cost': data['totals']['daily_cost']
    })

@app.route('/api/energy')
def api_energy():
    """API endpoint - returns nested JSON data"""
    return jsonify(get_energy_data())

@app.route('/diagnose')
def diagnose():
    """Diagnostic route to check API calls and data"""
    date = get_yesterday_date()
    
    # Test API credentials and endpoints
    results = {
        'date': date,
        'config': {
            'api_key_set': bool(API_KEY and API_KEY != 'sk_live_your_api_key_here'),
            'api_key_length': len(API_KEY) if API_KEY else 0,
            'electricity_mpan': ELECTRICITY_MPAN,
            'electricity_serial': ELECTRICITY_SERIAL,
            'gas_mprn': GAS_MPRN,
            'gas_serial': GAS_SERIAL
        }
    }
    
    # Test electricity API call
    try:
        elec_url = f"https://api.octopus.energy/v1/electricity-meter-points/{ELECTRICITY_MPAN}/meters/{ELECTRICITY_SERIAL}/consumption/"
        elec_params = {
            'period_from': f"{date}T00:00:00Z",
            'period_to': f"{date}T23:59:59Z",
            'page_size': 200
        }
        elec_response = requests.get(elec_url, params=elec_params, auth=(API_KEY, ''), timeout=30)
        results['electricity_api'] = {
            'status_code': elec_response.status_code,
            'success': elec_response.status_code == 200,
            'url': elec_url,
            'response_text': elec_response.text[:500] if elec_response.text else None
        }
        if elec_response.status_code == 200:
            elec_data = elec_response.json()
            results['electricity_api']['data_points'] = len(elec_data.get('results', []))
            results['electricity_api']['sample_data'] = elec_data.get('results', [])[:2]  # First 2 records
    except Exception as e:
        results['electricity_api'] = {
            'success': False,
            'error': str(e)
        }
    
    # Test gas API call
    try:
        gas_url = f"https://api.octopus.energy/v1/gas-meter-points/{GAS_MPRN}/meters/{GAS_SERIAL}/consumption/"
        gas_params = {
            'period_from': f"{date}T00:00:00Z",
            'period_to': f"{date}T23:59:59Z",
            'page_size': 200
        }
        gas_response = requests.get(gas_url, params=gas_params, auth=(API_KEY, ''), timeout=30)
        results['gas_api'] = {
            'status_code': gas_response.status_code,
            'success': gas_response.status_code == 200,
            'url': gas_url,
            'response_text': gas_response.text[:500] if gas_response.text else None
        }
        if gas_response.status_code == 200:
            gas_data = gas_response.json()
            results['gas_api']['data_points'] = len(gas_data.get('results', []))
            results['gas_api']['sample_data'] = gas_data.get('results', [])[:2]  # First 2 records
    except Exception as e:
        results['gas_api'] = {
            'success': False,
            'error': str(e)
        }
    
    return jsonify(results)

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    # For local development
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

#!/usr/bin/env python3
"""
Enhanced Octopus Energy Usage Tracker for TRMNL
Fetches electricity and gas consumption data and displays on TRMNL device
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

# Configuration
API_KEY = os.getenv('OCTOPUS_API_KEY', 'sk_live_your_api_key_here')
ELECTRICITY_MPAN = os.getenv('ELECTRICITY_MPAN', '1610018835487')
ELECTRICITY_SERIAL = os.getenv('ELECTRICITY_SERIAL', 'your_electricity_serial')
GAS_MPRN = os.getenv('GAS_MPRN', '1467503405')
GAS_SERIAL = os.getenv('GAS_SERIAL', 'your_gas_serial')

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

def make_api_request(url, auth):
    """Make API request with error handling"""
    try:
        response = requests.get(url, auth=auth, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None

def get_electricity_data(date):
    """Fetch electricity consumption data for a specific date"""
    url = f"https://api.octopus.energy/v1/electricity-meter-points/{ELECTRICITY_MPAN}/meters/{ELECTRICITY_SERIAL}/consumption/"
    params = {
        'period_from': f"{date}T00:00:00Z",
        'period_to': f"{date}T23:59:59Z",
        'page_size': 200
    }
    
    auth = (API_KEY, '')
    
    try:
        response = requests.get(url, params=params, auth=auth, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch electricity data: {e}")
        return None

def get_gas_data(date):
    """Fetch gas consumption data for a specific date"""
    url = f"https://api.octopus.energy/v1/gas-meter-points/{GAS_MPRN}/meters/{GAS_SERIAL}/consumption/"
    params = {
        'period_from': f"{date}T00:00:00Z",
        'period_to': f"{date}T23:59:59Z",
        'page_size': 200
    }
    
    auth = (API_KEY, '')
    
    try:
        response = requests.get(url, params=params, auth=auth, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch gas data: {e}")
        return None

def process_electricity_data(electricity_data):
    """Process electricity consumption data and calculate costs"""
    if not electricity_data or 'results' not in electricity_data:
        return {
            'total_usage': 0,
            'off_peak_usage': 0,
            'peak_usage': 0,
            'smart_charging_usage': 0,
            'total_cost': 0,
            'smart_charging_sessions': 0,
            'smart_charging_savings': 0
        }
    
    total_usage = 0
    off_peak_usage = 0
    peak_usage = 0
    smart_charging_usage = 0
    total_cost = 0
    smart_charging_sessions = 0
    smart_charging_savings = 0
    
    for reading in electricity_data['results']:
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
    
    return {
        'total_usage': round(total_usage, 2),
        'off_peak_usage': round(off_peak_usage, 2),
        'peak_usage': round(peak_usage, 2),
        'smart_charging_usage': round(smart_charging_usage, 2),
        'total_cost': round(total_cost, 2),
        'smart_charging_sessions': smart_charging_sessions,
        'smart_charging_savings': round(smart_charging_savings, 2)
    }

def process_gas_data(gas_data):
    """Process gas consumption data and convert to kWh"""
    if not gas_data or 'results' not in gas_data:
        return {
            'usage_m3': 0,
            'usage_kwh': 0,
            'cost': 0
        }
    
    total_usage_m3 = 0
    total_cost = 0
    
    for reading in gas_data['results']:
        consumption = reading.get('consumption', 0)
        total_usage_m3 += consumption
        # Calculate cost using current gas rate (approximate)
        total_cost += consumption * 0.1194  # Current gas rate per m³
    
    # Convert m³ to kWh
    total_usage_kwh = total_usage_m3 * GAS_CONVERSION_FACTOR
    
    return {
        'usage_m3': round(total_usage_m3, 3),
        'usage_kwh': round(total_usage_kwh, 2),
        'cost': round(total_cost, 2)
    }

@app.route('/')
def index():
    """Main route - shows energy usage data"""
    date = get_yesterday_date()
    
    # Fetch data
    electricity_data = get_electricity_data(date)
    gas_data = get_gas_data(date)
    
    # Process data
    electricity = process_electricity_data(electricity_data)
    gas = process_gas_data(gas_data)
    
    # Calculate totals
    total_cost = electricity['total_cost'] + gas['cost'] + ELECTRICITY_STANDING_CHARGE + GAS_STANDING_CHARGE
    
    return f"""
    <h1>Energy Usage - {date}</h1>
    
    <h2>⚡ Electricity</h2>
    <p>Total: {electricity['total_usage']} kWh (£{electricity['total_cost']:.2f})</p>
    <p>Off-peak: {electricity['off_peak_usage']} kWh</p>
    <p>Peak: {electricity['peak_usage']} kWh</p>
    <p>Smart charging: {electricity['smart_charging_usage']} kWh</p>
    <p>Standing charge: £{ELECTRICITY_STANDING_CHARGE:.2f}</p>
    
    <h2>🔥 Gas</h2>
    <p>Usage: {gas['usage_kwh']} kWh ({gas['usage_m3']} m³)</p>
    <p>Cost: £{gas['cost']:.2f}</p>
    <p>Standing charge: £{GAS_STANDING_CHARGE:.2f}</p>
    
    <h2>💷 Total</h2>
    <p>Daily total: £{total_cost:.2f}</p>
    <p>EV sessions: {electricity['smart_charging_sessions']}</p>
    """

@app.route('/trmnl')
def trmnl():
    """TRMNL endpoint - returns formatted data for display"""
    date = get_yesterday_date()
    
    # Fetch data
    electricity_data = get_electricity_data(date)
    gas_data = get_gas_data(date)
    
    # Process data
    electricity = process_electricity_data(electricity_data)
    gas = process_gas_data(gas_data)
    
    # Calculate totals
    total_cost = electricity['total_cost'] + gas['cost'] + ELECTRICITY_STANDING_CHARGE + GAS_STANDING_CHARGE
    
    # TRMNL template
    template = """
<div class="layout layout--col">
  {% if smart_charging_savings > 0 %}
  <div class="text--center" style="background: #e8f5e8; border: 1px solid #4caf50; border-radius: 4px; padding: 8px; margin-bottom: 8px;">
    <span class="title" style="color: #2e7d32;">🚗 Smart Charging Saved £{{ "%.2f"|format(smart_charging_savings) }}</span>
  </div>
  {% endif %}

  <div class="columns text--center">
    <div class="column">
      <div class="content">
        <span class="title">⚡ ELECTRICITY</span>
        <span class="value">{{ electricity_total_usage }} kWh £{{ "%.2f"|format(electricity_total_cost) }}</span>
        <span class="label">Off-Peak: {{ electricity_off_peak_usage }} kWh</span>
        <span class="label">Peak: {{ electricity_peak_usage }} kWh</span>
        {% if smart_charging_usage > 0 %}
        <span class="label" style="color: #2e7d32;">🚗 Smart: {{ smart_charging_usage }} kWh</span>
        {% else %}
        <span class="label">🚗 Smart: 0 kWh</span>
        {% endif %}
        <span class="label">Standing: £{{ "%.2f"|format(electricity_standing_charge) }}</span>
      </div>
    </div>
    
    <div class="column">
      <div class="content">
        <span class="title">🔥 GAS</span>
        <span class="value">{{ gas_usage_kwh }} kWh £{{ "%.2f"|format(gas_cost) }}</span>
        <span class="label">Usage: {{ gas_usage_kwh }} kWh</span>
        <span class="label">Standing: £{{ "%.2f"|format(gas_standing_charge) }}</span>
      </div>
    </div>
  </div>

  <div class="columns text--center">
    <div class="column">
      <div class="content">
        <span class="title">💷 DAILY TOTAL</span>
        <span class="value">£{{ "%.2f"|format(total_cost) }}</span>
      </div>
    </div>
    <div class="column">
      <div class="content">
        <span class="title">🚗 EV SESSIONS</span>
        <span class="value">{{ smart_charging_sessions }}</span>
      </div>
    </div>
  </div>
</div>

<div class="title_bar">
  <span class="title">Energy Usage - {{ date }}</span>
</div>
    """
    
    return render_template_string(
        template,
        date=date,
        electricity_total_usage=electricity['total_usage'],
        electricity_off_peak_usage=electricity['off_peak_usage'],
        electricity_peak_usage=electricity['peak_usage'],
        electricity_total_cost=electricity['total_cost'],
        electricity_standing_charge=ELECTRICITY_STANDING_CHARGE,
        gas_usage_kwh=gas['usage_kwh'],
        gas_cost=gas['cost'],
        gas_standing_charge=GAS_STANDING_CHARGE,
        smart_charging_usage=electricity['smart_charging_usage'],
        smart_charging_sessions=electricity['smart_charging_sessions'],
        smart_charging_savings=electricity['smart_charging_savings'],
        total_cost=total_cost
    )

@app.route('/api/energy')
def api_energy():
    """API endpoint - returns JSON data"""
    date = get_yesterday_date()
    
    # Fetch data
    electricity_data = get_electricity_data(date)
    gas_data = get_gas_data(date)
    
    # Process data
    electricity = process_electricity_data(electricity_data)
    gas = process_gas_data(gas_data)
    
    # Calculate totals
    total_cost = electricity['total_cost'] + gas['cost'] + ELECTRICITY_STANDING_CHARGE + GAS_STANDING_CHARGE
    
    return jsonify({
        'date': date,
        'electricity': {
            'total_usage': electricity['total_usage'],
            'off_peak_usage': electricity['off_peak_usage'],
            'peak_usage': electricity['peak_usage'],
            'smart_charging_usage': electricity['smart_charging_usage'],
            'total_cost': electricity['total_cost'],
            'standing_charge': ELECTRICITY_STANDING_CHARGE
        },
        'gas': {
            'usage_kwh': gas['usage_kwh'],
            'usage_m3': gas['usage_m3'],
            'cost': gas['cost'],
            'standing_charge': GAS_STANDING_CHARGE
        },
        'smart_charging': {
            'sessions': electricity['smart_charging_sessions'],
            'savings': electricity['smart_charging_savings']
        },
        'totals': {
            'daily_cost': total_cost
        }
    })

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    # For local development
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

#!/usr/bin/env python3

from flask import Flask, jsonify, request, make_response
import requests
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
import logging
from typing import Optional, Dict, Any, Tuple
from functools import wraps

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

# Constants
BASE_URL = "https://api.octopus.energy"
GAS_M3_TO_KWH = 11.1868  # Gas conversion factor: m³ to kWh
OFF_PEAK_START_HOUR = 23
OFF_PEAK_START_MINUTE = 30
OFF_PEAK_END_HOUR = 5
OFF_PEAK_END_MINUTE = 30
API_TIMEOUT = 10  # seconds
MAX_PAGE_SIZE = 200

# Set up logging for production
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def is_off_peak_period(dt: datetime) -> bool:
    """
    Check if datetime falls in off-peak period (23:30-05:30) for Octopus Go tariff.
    
    Args:
        dt: Datetime to check
        
    Returns:
        True if the time falls within off-peak period
    """
    hour, minute = dt.hour, dt.minute
    return (
        (hour == OFF_PEAK_START_HOUR and minute >= OFF_PEAK_START_MINUTE) or
        (hour < OFF_PEAK_END_HOUR) or
        (hour == OFF_PEAK_END_HOUR and minute < OFF_PEAK_END_MINUTE)
    )


def get_date_range_yesterday() -> Tuple[datetime, datetime]:
    """
    Get the date range for yesterday (00:00 to 00:00 next day) in local time.

    Uses naive local time (no timezone) for compatibility with Octopus Energy API,
    which expects local UK time for gas meter queries.

    Returns:
        Tuple of (yesterday_start, today_start) datetimes in local time
    """
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    return yesterday_start, today_start


def make_octopus_request(endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Make an authenticated request to the Octopus Energy API.
    
    Args:
        endpoint: API endpoint path
        params: Query parameters
        
    Returns:
        JSON response data or None on error
    """
    try:
        session = requests.Session()
        session.auth = (API_KEY, '')
        
        url = BASE_URL + endpoint
        response = session.get(url, params=params, timeout=API_TIMEOUT)
        response.raise_for_status()
        
        return response.json()
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed for {endpoint}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in API request: {e}")
        return None


def get_electricity_usage_by_time(mpan: str, serial: str, use_mock: bool = False, include_raw: bool = False) -> Optional[Dict[str, Any]]:
    """
    Get electricity usage split by off-peak and peak periods for yesterday.

    Args:
        mpan: Electricity meter point administration number
        serial: Meter serial number
        use_mock: If True, return mock data for testing
        include_raw: If True, include raw API response in return value

    Returns:
        Dictionary with off_peak_usage, peak_usage, and total_usage in kWh,
        and optionally raw_response from API, or None on error
    """
    if use_mock:
        mock_data = {
            'off_peak_usage': 6.2,
            'peak_usage': 2.3,
            'total_usage': 8.5
        }
        if include_raw:
            mock_data['raw_response'] = {'count': 48, 'results': [{'consumption': 0.129, 'interval_start': '2024-01-01T23:30:00Z'}]}
        return mock_data
    
    yesterday_start, today_start = get_date_range_yesterday()

    endpoint = f"/v1/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
    params = {
        'period_from': yesterday_start.isoformat(),
        'period_to': today_start.isoformat(),
        'page_size': 100
    }

    data = make_octopus_request(endpoint, params)
    if data is None:
        return None

    results = data.get('results', [])

    if not results:
        logger.warning("No electricity readings found for yesterday")
        result_data = {
            'off_peak_usage': 0.0,
            'peak_usage': 0.0,
            'total_usage': 0.0
        }
        if include_raw:
            result_data['raw_response'] = data
            result_data['query_params'] = params
        return result_data

    off_peak_usage = 0.0
    peak_usage = 0.0

    for reading in results:
        try:
            interval_start = datetime.fromisoformat(reading['interval_start'].replace('Z', '+00:00'))
            consumption = float(reading['consumption'])

            if is_off_peak_period(interval_start):
                off_peak_usage += consumption
            else:
                peak_usage += consumption

        except (KeyError, ValueError) as e:
            logger.warning(f"Skipping invalid reading: {e}")
            continue

    total_usage = off_peak_usage + peak_usage

    logger.info(f"Electricity usage - Off-peak: {off_peak_usage:.2f} kWh, Peak: {peak_usage:.2f} kWh")

    result_data = {
        'off_peak_usage': round(off_peak_usage, 2),
        'peak_usage': round(peak_usage, 2),
        'total_usage': round(total_usage, 2)
    }

    if include_raw:
        result_data['raw_response'] = data
        result_data['query_params'] = params

    return result_data


def get_gas_usage(mprn: str, serial: str, use_mock: bool = False, include_raw: bool = False) -> Optional[Any]:
    """
    Get gas usage for yesterday in kWh.

    If no usage is found for yesterday, returns 7-day average.

    Args:
        mprn: Gas meter point reference number
        serial: Meter serial number
        use_mock: If True, return mock data for testing
        include_raw: If True, return dict with usage and raw API response

    Returns:
        Gas usage in kWh (float), or dict with usage and raw_response if include_raw=True,
        or None on error
    """
    if use_mock:
        if include_raw:
            return {
                'usage': 44.5,
                'raw_response': {'count': 1, 'results': [{'consumption': 3.979, 'interval_start': '2024-01-01T00:00:00Z'}]}
            }
        return 44.5
    
    yesterday_start, today_start = get_date_range_yesterday()

    endpoint = f"/v1/gas-meter-points/{mprn}/meters/{serial}/consumption/"
    params = {
        'period_from': yesterday_start.isoformat(),
        'period_to': today_start.isoformat(),
        'page_size': 100
    }

    data = make_octopus_request(endpoint, params)
    if data is None:
        return None

    results = data.get('results', [])
    logger.info(f"Gas API returned {len(results)} readings")

    if results:
        # Log sample readings for debugging
        for i, reading in enumerate(results[:3]):
            logger.info(f"Sample reading {i+1}: {reading.get('consumption', 'N/A')} m³ at {reading.get('interval_start', 'N/A')}")

        # Sum all readings - API already filtered by date
        total_consumption_m3 = sum(float(reading['consumption']) for reading in results)
        logger.info(f"Total m³: {total_consumption_m3:.3f}")

        # Convert to kWh
        total_consumption_kwh = total_consumption_m3 * GAS_M3_TO_KWH
        logger.info(f"Total kWh: {total_consumption_kwh:.2f}")

        # If zero, try 7-day average
        if total_consumption_m3 == 0:
            logger.info("No gas usage yesterday, calculating 7-day average...")
            avg_usage = get_gas_weekly_average(mprn, serial, today_start)
            if include_raw:
                return {
                    'usage': avg_usage,
                    'raw_response': data,
                    'query_params': params,
                    'is_average': True
                }
            return avg_usage

        usage_kwh = round(total_consumption_kwh, 2) if total_consumption_kwh > 0 else 0.0

        if include_raw:
            return {
                'usage': usage_kwh,
                'raw_response': data,
                'query_params': params,
                'is_average': False
            }
        return usage_kwh
    else:
        logger.warning("No gas readings found for yesterday")
        if include_raw:
            return {
                'usage': 0.0,
                'raw_response': data,
                'query_params': params,
                'is_average': False
            }
        return 0.0


def get_gas_weekly_average(mprn: str, serial: str, today_start: datetime) -> float:
    """
    Get 7-day average gas usage when yesterday's usage is zero.
    
    Args:
        mprn: Gas meter point reference number
        serial: Meter serial number
        today_start: Start of today (for date range calculation)
        
    Returns:
        Daily average gas usage in kWh
    """
    week_ago = today_start - timedelta(days=7)
    endpoint = f"/v1/gas-meter-points/{mprn}/meters/{serial}/consumption/"
    params = {
        'period_from': week_ago.isoformat(),
        'period_to': today_start.isoformat(),
        'page_size': MAX_PAGE_SIZE
    }
    
    data = make_octopus_request(endpoint, params)
    if data is None:
        return 0.0
    
    results = data.get('results', [])
    
    if results:
        total_week_m3 = sum(float(reading['consumption']) for reading in results)
        total_week_kwh = total_week_m3 * GAS_M3_TO_KWH
        daily_average_kwh = total_week_kwh / 7
        logger.info(f"7-day average: {daily_average_kwh:.2f} kWh/day")
        return round(daily_average_kwh, 2)
    
    return 0.0


def calculate_costs(electricity_data: Dict[str, float], gas_usage: float) -> Dict[str, Any]:
    """
    Calculate all costs based on usage data and tariff rates.
    
    Args:
        electricity_data: Dictionary with off_peak_usage, peak_usage, total_usage
        gas_usage: Gas usage in kWh
        
    Returns:
        Dictionary containing all calculated costs
    """
    off_peak_cost = round(electricity_data['off_peak_usage'] * ELECTRICITY_RATE_OFF_PEAK, 2)
    peak_cost = round(electricity_data['peak_usage'] * ELECTRICITY_RATE_PEAK, 2)
    total_electricity_cost = round(off_peak_cost + peak_cost + STANDING_CHARGE_ELECTRICITY, 2)
    
    gas_usage_cost = round(gas_usage * GAS_RATE, 2)
    gas_cost = round(gas_usage_cost + STANDING_CHARGE_GAS, 2)
    
    total_cost = round(total_electricity_cost + gas_cost, 2)
    
    return {
        'off_peak_cost': off_peak_cost,
        'peak_cost': peak_cost,
        'total_electricity_cost': total_electricity_cost,
        'gas_usage_cost': gas_usage_cost,
        'gas_cost': gas_cost,
        'total_cost': total_cost
    }


def validate_mock_param(value: str) -> bool:
    """Validate the mock query parameter."""
    return value.lower() in ('true', '1', 'yes')


@app.route('/')
def index():
    """Home page with test links and current tariff information."""
    return f'''
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>TRMNL Energy Plugin</title>
    </head>
    <body style="font-family: Arial, sans-serif; margin: 40px; max-width: 800px;">
        <h1>TRMNL Energy Plugin</h1>
        <h2>Test Links:</h2>
        <ul>
            <li><a href="/api/energy?mock=true">API Test (Mock Data)</a></li>
            <li><a href="/api/energy">API Test (Live Data)</a></li>
            <li><a href="/trmnl?mock=true">TRMNL Display (Mock)</a></li>
            <li><a href="/trmnl">TRMNL Display (Live)</a></li>
            <li><a href="/trmnl-html?mock=true">HTML Display (Mock)</a></li>
            <li><a href="/trmnl-html">HTML Display (Live)</a></li>
            <li><a href="/health">Health Check</a></li>
        </ul>

        <h2>Debug Links (Raw API Data):</h2>
        <ul>
            <li><a href="/debug?mock=true">Debug View (Mock Data)</a> - View raw API responses with mock data</li>
            <li><a href="/debug">Debug View (Live Data)</a> - View raw API responses from Octopus Energy</li>
            <li><a href="/api/raw-data?mock=true">Raw API JSON (Mock)</a> - JSON format of raw API data</li>
            <li><a href="/api/raw-data">Raw API JSON (Live)</a> - JSON format of raw API data from Octopus Energy</li>
        </ul>
        
        <h3>Current Tariff Rates (Octopus Go):</h3>
        <table style="border-collapse: collapse; width: 100%;">
            <tr style="background: #f0f0f0;">
                <th style="text-align: left; padding: 8px; border: 1px solid #ddd;">Item</th>
                <th style="text-align: right; padding: 8px; border: 1px solid #ddd;">Rate</th>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">Electricity Off-Peak (23:30-05:30)</td>
                <td style="text-align: right; padding: 8px; border: 1px solid #ddd;">{ELECTRICITY_RATE_OFF_PEAK}p/kWh</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">Electricity Peak (05:30-23:30)</td>
                <td style="text-align: right; padding: 8px; border: 1px solid #ddd;">{ELECTRICITY_RATE_PEAK}p/kWh</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">Gas</td>
                <td style="text-align: right; padding: 8px; border: 1px solid #ddd;">{GAS_RATE}p/kWh</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">Electricity Standing Charge</td>
                <td style="text-align: right; padding: 8px; border: 1px solid #ddd;">{STANDING_CHARGE_ELECTRICITY}p/day</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">Gas Standing Charge</td>
                <td style="text-align: right; padding: 8px; border: 1px solid #ddd;">{STANDING_CHARGE_GAS}p/day</td>
            </tr>
        </table>
        
        <h3>About:</h3>
        <p>This service fetches energy usage data from Octopus Energy API and formats it for display on TRMNL devices.</p>
    </body>
    </html>
    '''


@app.route('/api/energy')
def energy_data():
    """
    API endpoint returning detailed energy usage and cost data.
    
    Query Parameters:
        mock (str): Set to 'true' to return mock data for testing
        
    Returns:
        JSON object with electricity and gas usage/cost details
    """
    use_mock = validate_mock_param(request.args.get('mock', 'false'))
    
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_str = yesterday.strftime("%d %b %Y")
    
    electricity_data = get_electricity_usage_by_time(ELECTRICITY_MPAN, ELECTRICITY_SERIAL, use_mock)
    gas_usage = get_gas_usage(GAS_MPRN, GAS_SERIAL, use_mock)
    
    if electricity_data is None or gas_usage is None:
        return jsonify({
            "date": date_str,
            "error": "Failed to fetch data from Octopus Energy API",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 500
    
    costs = calculate_costs(electricity_data, gas_usage)
    
    return jsonify({
        "date": date_str,
        "electricity": {
            "off_peak": {
                "usage": electricity_data['off_peak_usage'],
                "rate": ELECTRICITY_RATE_OFF_PEAK,
                "cost": costs['off_peak_cost'],
                "period": "23:30-05:30"
            },
            "peak": {
                "usage": electricity_data['peak_usage'],
                "rate": ELECTRICITY_RATE_PEAK,
                "cost": costs['peak_cost'],
                "period": "05:30-23:30"
            },
            "total_usage": electricity_data['total_usage'],
            "total_cost": costs['total_electricity_cost'],
            "standing_charge": STANDING_CHARGE_ELECTRICITY,
            "unit": "kWh"
        },
        "gas": {
            "usage": gas_usage,
            "rate": GAS_RATE,
            "cost": costs['gas_cost'],
            "standing_charge": STANDING_CHARGE_GAS,
            "unit": "kWh"
        },
        "total_cost": costs['total_cost'],
        "currency": "GBP",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mock_data": use_mock
    })


@app.route('/trmnl')
def trmnl_display():
    """
    TRMNL JSON endpoint - returns flat JSON data for TRMNL markup templates.
    
    Query Parameters:
        mock (str): Set to 'true' to return mock data for testing
        
    Returns:
        JSON object with flat structure suitable for TRMNL templates
    """
    use_mock = validate_mock_param(request.args.get('mock', 'false'))
    
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_str = yesterday.strftime("%d %b %Y")
    
    electricity_data = get_electricity_usage_by_time(ELECTRICITY_MPAN, ELECTRICITY_SERIAL, use_mock)
    gas_usage = get_gas_usage(GAS_MPRN, GAS_SERIAL, use_mock)
    
    if electricity_data is None or gas_usage is None:
        response_data = {
            "date": date_str,
            "error": "Failed to fetch data from Octopus Energy API",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    else:
        costs = calculate_costs(electricity_data, gas_usage)
        
        response_data = {
            "date": date_str,
            "electricity_off_peak_usage": electricity_data['off_peak_usage'],
            "electricity_off_peak_cost": f"{costs['off_peak_cost']:.2f}",
            "electricity_peak_usage": electricity_data['peak_usage'],
            "electricity_peak_cost": f"{costs['peak_cost']:.2f}",
            "electricity_total_usage": electricity_data['total_usage'],
            "electricity_total_cost": f"{costs['total_electricity_cost']:.2f}",
            "electricity_standing_charge": f"{STANDING_CHARGE_ELECTRICITY:.2f}",
            "gas_usage": gas_usage,
            "gas_usage_only_cost": f"{costs['gas_usage_cost']:.2f}",
            "gas_cost": f"{costs['gas_cost']:.2f}",
            "gas_standing_charge": f"{STANDING_CHARGE_GAS:.2f}",
            "total_cost": f"{costs['total_cost']:.2f}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mock_data": use_mock
        }
    
    response = make_response(jsonify(response_data))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response


@app.route('/trmnl-html')
def trmnl_html():
    """
    TRMNL HTML endpoint - returns complete HTML page for display testing.
    
    Query Parameters:
        mock (str): Set to 'true' to use mock data
        
    Returns:
        HTML page that fetches and displays energy data
    """
    use_mock = request.args.get('mock', 'false')
    api_url = f'/api/energy?mock={use_mock}' if validate_mock_param(use_mock) else '/api/energy'
    
    html_template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
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
            .error {
                text-align: center;
                color: red;
                padding: 20px;
            }
        </style>
    </head>
    <body>
        <div class="header">Energy Usage</div>
        <div id="content">Loading...</div>
        
        <script>
            fetch('API_URL_PLACEHOLDER')
                .then(response => {
                    if (!response.ok) {
                        throw new Error('API request failed');
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.error) {
                        document.getElementById('content').innerHTML = 
                            '<div class="error">Error: ' + data.error + '</div>';
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
                        '<div class="usage-row"><span>Standing Charge</span><span>£' + elec.standing_charge.toFixed(2) + '</span></div>' +
                        '<div class="total-row"><span>Total: ' + elec.total_usage + ' kWh</span><span>£' + elec.total_cost.toFixed(2) + '</span></div>' +
                        '</div>';
                    
                    // Gas section
                    const gasUsageCost = (gas.usage * gas.rate).toFixed(2);
                    const gasDisplayUsage = gas.usage > 0 ? gas.usage.toFixed(1) + ' kWh' : '0.0 kWh';
                    
                    content += '<div class="section">' +
                        '<div class="section-title">GAS</div>' +
                        '<div class="usage-row"><span>Usage: ' + gasDisplayUsage + '</span><span>£' + gasUsageCost + '</span></div>' +
                        '<div class="usage-row"><span>Standing Charge</span><span>£' + gas.standing_charge.toFixed(2) + '</span></div>' +
                        '<div class="total-row"><span>Total: ' + gasDisplayUsage + '</span><span>£' + gas.cost.toFixed(2) + '</span></div>' +
                        '</div>';
                    
                    // Grand total
                    content += '<div class="grand-total">DAILY TOTAL<br>£' + parseFloat(data.total_cost).toFixed(2) + '</div>';
                    
                    // Footer 
                    let footerText = data.mock_data ? 'Mock Data' : 'Updated: ' + new Date(data.timestamp).toLocaleString();
                    content += '<div class="footer">' + footerText + '</div>';
                    
                    document.getElementById('content').innerHTML = content;
                })
                .catch(error => {
                    console.error('Error:', error);
                    document.getElementById('content').innerHTML = 
                        '<div class="error">Error loading data. Please try again.</div>';
                });
        </script>
    </body>
    </html>
    '''
    
    return html_template.replace('API_URL_PLACEHOLDER', api_url)


@app.route('/api/raw-data')
def raw_api_data():
    """
    Debug endpoint that returns raw API responses from Octopus Energy.

    Query Parameters:
        mock (str): Set to 'true' to return mock data for testing

    Returns:
        JSON object with raw API responses and query parameters
    """
    use_mock = validate_mock_param(request.args.get('mock', 'false'))

    yesterday_start, today_start = get_date_range_yesterday()

    # Get electricity data with raw API response
    electricity_data = get_electricity_usage_by_time(
        ELECTRICITY_MPAN,
        ELECTRICITY_SERIAL,
        use_mock,
        include_raw=True
    )

    # Get gas data with raw API response
    gas_data = get_gas_usage(
        GAS_MPRN,
        GAS_SERIAL,
        use_mock,
        include_raw=True
    )

    if electricity_data is None or gas_data is None:
        return jsonify({
            "error": "Failed to fetch data from Octopus Energy API",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 500

    # Extract usage values
    if isinstance(gas_data, dict):
        gas_usage = gas_data.get('usage', 0.0)
    else:
        gas_usage = gas_data

    return jsonify({
        "date_range": {
            "from": yesterday_start.isoformat(),
            "to": today_start.isoformat()
        },
        "electricity": {
            "processed_data": {
                "off_peak_usage": electricity_data.get('off_peak_usage', 0.0),
                "peak_usage": electricity_data.get('peak_usage', 0.0),
                "total_usage": electricity_data.get('total_usage', 0.0)
            },
            "raw_api_response": electricity_data.get('raw_response', {}),
            "query_params": electricity_data.get('query_params', {})
        },
        "gas": {
            "processed_data": {
                "usage_kwh": gas_usage,
                "is_average": gas_data.get('is_average', False) if isinstance(gas_data, dict) else False
            },
            "raw_api_response": gas_data.get('raw_response', {}) if isinstance(gas_data, dict) else {},
            "query_params": gas_data.get('query_params', {}) if isinstance(gas_data, dict) else {}
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mock_data": use_mock
    })


@app.route('/debug')
def debug_display():
    """
    Debug HTML page showing raw API data in a readable format.

    Query Parameters:
        mock (str): Set to 'true' to use mock data

    Returns:
        HTML page displaying raw API responses
    """
    use_mock = request.args.get('mock', 'false')
    api_url = f'/api/raw-data?mock={use_mock}' if validate_mock_param(use_mock) else '/api/raw-data'

    html_template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>API Debug View</title>
        <style>
            body {
                font-family: 'Courier New', monospace;
                margin: 20px;
                background: #1e1e1e;
                color: #d4d4d4;
            }
            .header {
                font-size: 24px;
                font-weight: bold;
                margin-bottom: 20px;
                color: #4ec9b0;
                border-bottom: 2px solid #4ec9b0;
                padding-bottom: 10px;
            }
            .section {
                margin: 20px 0;
                padding: 15px;
                background: #252526;
                border-left: 4px solid #007acc;
                border-radius: 4px;
            }
            .section-title {
                font-size: 18px;
                font-weight: bold;
                margin-bottom: 10px;
                color: #569cd6;
            }
            .data-row {
                margin: 8px 0;
                padding: 5px;
                background: #1e1e1e;
                border-radius: 3px;
            }
            .label {
                color: #9cdcfe;
                font-weight: bold;
            }
            .value {
                color: #ce9178;
            }
            pre {
                background: #1e1e1e;
                padding: 15px;
                border-radius: 5px;
                overflow-x: auto;
                border: 1px solid #3c3c3c;
                color: #d4d4d4;
            }
            .error {
                color: #f48771;
                padding: 20px;
                text-align: center;
            }
            .info-box {
                background: #264f78;
                padding: 10px;
                margin: 10px 0;
                border-radius: 4px;
                border-left: 4px solid #007acc;
            }
            .warning-box {
                background: #433620;
                padding: 10px;
                margin: 10px 0;
                border-radius: 4px;
                border-left: 4px solid #d7ba7d;
            }
        </style>
    </head>
    <body>
        <div class="header">🔍 API Debug View - Raw Data</div>
        <div id="content">Loading...</div>

        <script>
            fetch('API_URL_PLACEHOLDER')
                .then(response => {
                    if (!response.ok) {
                        throw new Error('API request failed');
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.error) {
                        document.getElementById('content').innerHTML =
                            '<div class="error">Error: ' + data.error + '</div>';
                        return;
                    }

                    let content = '';

                    // Date range info
                    content += '<div class="info-box">';
                    content += '<div class="label">Date Range:</div>';
                    content += '<div class="value">From: ' + data.date_range.from + '</div>';
                    content += '<div class="value">To: ' + data.date_range.to + '</div>';
                    content += '</div>';

                    if (data.mock_data) {
                        content += '<div class="warning-box"><strong>⚠️ Using Mock Data</strong></div>';
                    }

                    // Electricity Section
                    content += '<div class="section">';
                    content += '<div class="section-title">⚡ ELECTRICITY DATA</div>';

                    content += '<div class="data-row"><span class="label">Off-Peak Usage:</span> <span class="value">' +
                        data.electricity.processed_data.off_peak_usage + ' kWh</span></div>';
                    content += '<div class="data-row"><span class="label">Peak Usage:</span> <span class="value">' +
                        data.electricity.processed_data.peak_usage + ' kWh</span></div>';
                    content += '<div class="data-row"><span class="label">Total Usage:</span> <span class="value">' +
                        data.electricity.processed_data.total_usage + ' kWh</span></div>';

                    content += '<h4 style="color: #4ec9b0; margin-top: 15px;">Query Parameters:</h4>';
                    content += '<pre>' + JSON.stringify(data.electricity.query_params, null, 2) + '</pre>';

                    content += '<h4 style="color: #4ec9b0; margin-top: 15px;">Raw API Response:</h4>';
                    const elecResults = data.electricity.raw_api_response.results || [];
                    content += '<div class="data-row"><span class="label">Total Records:</span> <span class="value">' +
                        elecResults.length + '</span></div>';
                    content += '<pre>' + JSON.stringify(data.electricity.raw_api_response, null, 2) + '</pre>';
                    content += '</div>';

                    // Gas Section
                    content += '<div class="section">';
                    content += '<div class="section-title">🔥 GAS DATA</div>';

                    content += '<div class="data-row"><span class="label">Usage (kWh):</span> <span class="value">' +
                        data.gas.processed_data.usage_kwh + ' kWh</span></div>';

                    if (data.gas.processed_data.is_average) {
                        content += '<div class="warning-box"><strong>⚠️ This is a 7-day average (no usage found for yesterday)</strong></div>';
                    }

                    content += '<h4 style="color: #4ec9b0; margin-top: 15px;">Query Parameters:</h4>';
                    content += '<pre>' + JSON.stringify(data.gas.query_params, null, 2) + '</pre>';

                    content += '<h4 style="color: #4ec9b0; margin-top: 15px;">Raw API Response:</h4>';
                    const gasResults = data.gas.raw_api_response.results || [];
                    content += '<div class="data-row"><span class="label">Total Records:</span> <span class="value">' +
                        gasResults.length + '</span></div>';
                    content += '<pre>' + JSON.stringify(data.gas.raw_api_response, null, 2) + '</pre>';
                    content += '</div>';

                    // Timestamp
                    content += '<div class="info-box" style="text-align: center; margin-top: 20px;">';
                    content += '<small>Last Updated: ' + new Date(data.timestamp).toLocaleString() + '</small>';
                    content += '</div>';

                    document.getElementById('content').innerHTML = content;
                })
                .catch(error => {
                    console.error('Error:', error);
                    document.getElementById('content').innerHTML =
                        '<div class="error">Error loading data. Please try again.</div>';
                });
        </script>
    </body>
    </html>
    '''

    return html_template.replace('API_URL_PLACEHOLDER', api_url)


@app.route('/health')
def health_check():
    """
    Health check endpoint for monitoring.

    Returns:
        JSON object with status and timestamp
    """
    return jsonify({
        "status": "ok",
        "service": "TRMNL Octopus Energy Plugin",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


if __name__ == '__main__':
    logger.info("Starting TRMNL Octopus Energy Plugin server")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

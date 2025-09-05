# TRMNL Octopus Energy Plugin - Intelligent Octopus Go

A Flask web application that provides energy usage data from Octopus Energy API for display on TRMNL e-ink devices. **Now with Intelligent Octopus Go support** for smart EV charging detection and savings tracking.

## 🚗 New! Intelligent Octopus Go Features

This plugin now supports **Intelligent Octopus Go** customers with:

- **Smart Charging Detection**: Automatically identifies when your EV was charged outside normal off-peak hours but still billed at the cheap 7p rate
- **Dispatch Tracking**: Monitors planned and completed intelligent dispatch periods
- **Savings Calculation**: Shows exactly how much you saved through smart charging vs. peak rates
- **Enhanced Display**: Visual highlighting of smart charging sessions with session counts

### What is Intelligent Octopus Go?

Intelligent Octopus Go is Octopus Energy's smart EV tariff that:
- Provides 6 hours of cheap electricity (7p/kWh) every night between 23:30-05:30
- **Automatically schedules EV charging** when energy is cheapest and greenest
- **Bills smart charging at 7p/kWh even outside the normal off-peak window**
- Saves money and reduces carbon footprint

## 📊 Features

### Energy Data Display
- **Peak usage** (05:30-23:30) at your peak rate
- **Standard off-peak** (23:30-05:30) at 7p/kWh
- **Smart charging usage** (intelligent dispatch periods) at 7p/kWh ⚡
- **Gas consumption** with costs
- **Daily savings** from smart charging

### API Endpoints
- `/api/energy` - JSON energy data with intelligent dispatch info
- `/trmnl` - Formatted HTML for TRMNL devices
- `/dispatches` - View recent smart charging schedules
- `/health` - Service health check
- Mock data support for testing

### TRMNL Display Features
- **Green highlighting** for smart charging sessions
- **Savings alerts** when smart charging saves money
- **Session counter** showing number of EV charging sessions
- **Dispatch detection** indicator in footer
- **Responsive design** optimized for e-ink displays

## 🔧 Setup

### Prerequisites
- Python 3.8+
- Octopus Energy account with API access
- Smart meter with half-hourly data
- For Intelligent features: Intelligent Octopus Go tariff

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/marksankey/Energy_Usage.git
   cd Energy_Usage
   ```

2. **Create virtual environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On macOS/Linux
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   Create a `.env` file with:
   ```bash
   # Octopus Energy API
   API_KEY=sk_live_YOUR_API_KEY_HERE
   ELECTRICITY_MPAN=YOUR_MPAN_NUMBER
   ELECTRICITY_SERIAL=YOUR_METER_SERIAL
   GAS_MPRN=YOUR_MPRN_NUMBER
   GAS_SERIAL=YOUR_GAS_METER_SERIAL
   
   # Intelligent Octopus Go Tariff Rates (in pounds)
   ELECTRICITY_RATE_PEAK=0.2957
   ELECTRICITY_RATE_OFF_PEAK=0.0700
   GAS_RATE=0.0626
   STANDING_CHARGE_ELECTRICITY=0.4734
   STANDING_CHARGE_GAS=0.2971
   ```

### Getting Your Credentials

#### Octopus Energy API Key
1. Log into your Octopus Energy account
2. Go to the "Developer" section
3. Generate an API key

#### Meter Details
1. Check your Octopus Energy bill or account dashboard
2. Find your **MPAN** (electricity) and **MPRN** (gas) numbers
3. Note your meter serial numbers

## 🚀 Running the Application

### Development
```bash
source venv/bin/activate
python3 app.py
```

### Production
```bash
source venv/bin/activate
python3 production_app.py
```

The application will start on `http://localhost:5000`

## 📱 Usage

### Test Endpoints
- `http://localhost:5000/` - Main page with test links
- `http://localhost:5000/api/energy` - Live energy data JSON
- `http://localhost:5000/api/energy?mock=true` - Mock data for testing
- `http://localhost:5000/trmnl` - TRMNL-formatted display
- `http://localhost:5000/dispatches` - View recent dispatch schedules
- `http://localhost:5000/health` - Health check

### TRMNL Integration

For your TRMNL device:
1. Create a new custom plugin
2. Set the data source to your deployed app URL + `/trmnl`
3. Configure refresh interval (recommended: every 4 hours)

## 📊 Enhanced Data Structure

The `/api/energy` endpoint now returns smart charging data:

```json
{
  "date": "05 Sep 2025",
  "electricity": {
    "off_peak": {
      "usage": 6.2,
      "rate": 0.07,
      "cost": 0.43,
      "period": "23:30-05:30"
    },
    "peak": {
      "usage": 2.3, 
      "rate": 0.2957,
      "cost": 0.68,
      "period": "05:30-23:30"
    },
    "smart_charging": {
      "usage": 1.8,
      "rate": 0.07,
      "cost": 0.13,
      "sessions": 2,
      "savings": 0.41,
      "period": "Intelligent dispatch"
    },
    "total_usage": 10.3,
    "total_cost": 1.71
  },
  "intelligent_features": {
    "dispatch_periods_found": 3,
    "smart_charging_active": true,
    "total_savings": 0.41
  }
}
```

## 🔍 How Intelligent Detection Works

### Smart Charging Detection
1. **GraphQL API**: Connects to Octopus's GraphQL API to fetch dispatch schedules
2. **Planned Dispatches**: Shows upcoming smart charging windows
3. **Completed Dispatches**: Tracks actual charging sessions
4. **Consumption Analysis**: Cross-references energy usage with dispatch periods
5. **Rate Application**: Automatically applies 7p rate to smart charging periods

### Billing Accuracy
The plugin ensures accurate billing by:
- ✅ **Standard off-peak** (23:30-05:30): 7p/kWh
- ✅ **Peak periods** (05:30-23:30): Peak rate
- ✅ **Smart charging** (any time): 7p/kWh when dispatched by Octopus
- ✅ **Savings calculation**: Shows money saved vs. peak rates

## 🚀 Deployment

### Heroku (Recommended)
1. Create a Heroku app
2. Set environment variables in Heroku dashboard
3. Deploy using git:
   ```bash
   git push heroku main
   ```

### Render
1. Connect your GitHub repository
2. Set environment variables
3. Deploy as a web service

### Environment Variables for Deployment
Ensure all `.env` variables are set in your deployment platform:
- `API_KEY`
- `ELECTRICITY_MPAN`
- `ELECTRICITY_SERIAL`
- `GAS_MPRN`
- `GAS_SERIAL`
- Tariff rates (if different from defaults)

## 📋 Requirements

### For Basic Functionality
- Octopus Energy customer account
- Smart meter with half-hourly readings
- Internet connection for API access

### For Intelligent Features
- **Intelligent Octopus Go tariff**
- **Compatible EV charger** (or Tesla/supported vehicle)
- **Smart charging enabled** in Octopus app

### Supported Configurations
- ✅ Intelligent Octopus Go with any compatible EV
- ✅ Standard Octopus Go (basic peak/off-peak only)
- ✅ Other Octopus tariffs (may need rate adjustments)

## ⚠️ Important Notes

### Data Availability
- **Smart meter data**: Usually 1-2 days behind
- **Dispatch data**: Real-time for planned, recent for completed
- **New installations**: May take several days for data to appear

### Billing Accuracy
- The plugin shows estimated costs based on consumption and dispatch data
- **Your actual bill from Octopus Energy is always authoritative**
- Contact Octopus if you notice discrepancies in smart charging billing

### Rate Limits
- GraphQL API: Reasonable usage limits apply
- REST API: Standard rate limits
- Recommended refresh: Every 4 hours for TRMNL

## 🆘 Support

### Common Issues

**"No dispatch data found"**
- Ensure you're on Intelligent Octopus Go tariff
- Check that smart charging is enabled in the Octopus app
- Verify your EV charger is compatible and online

**"No consumption data"**
- Check your meter details (MPAN, MPRN, serials)
- Verify your smart meter is communicating
- Data may be 1-2 days behind

**"GraphQL errors"**
- Verify your API key is correct
- Check internet connection
- Try again later if Octopus APIs are experiencing issues

### Getting Help
- Check Octopus Energy community forums
- Review this README and test with mock data first
- Create GitHub issues for bugs or feature requests

## 🔗 Useful Links

- [Octopus Energy API Documentation](https://developer.octopus.energy/)
- [Intelligent Octopus Go Information](https://octopus.energy/smart/intelligent-octopus-go/)
- [TRMNL Device Support](https://usetrmnl.com/)
- [Octopus Energy Community](https://forum.octopus.energy/)

---

**💡 Pro Tip**: Use the `/api/energy?mock=true` endpoint to test your TRMNL plugin setup before configuring with live data!

**🚗 EV Owners**: This plugin helps you track exactly how much you're saving with Intelligent Octopus Go's smart charging feature!

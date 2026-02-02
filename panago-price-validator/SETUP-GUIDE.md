# Panago Price Validator - Setup Guide

## Step 1: Install Docker Desktop

Download and install Docker Desktop for your system:

**Windows:** https://docs.docker.com/desktop/install/windows-install/

**Mac:** https://docs.docker.com/desktop/install/mac-install/

After installing:
1. Open Docker Desktop
2. Wait for it to say "Docker is running" (green icon in system tray)
3. Keep Docker Desktop running while using the validator

## Step 2: Download the Validator

1. Download the validator zip file (provided by your team lead)
2. Extract the zip to a folder (e.g., `C:\panago-validator` or `~/panago-validator`)

## Step 3: Start the Validator

**Windows:**
1. Open the extracted folder
2. Double-click `start.bat`
3. Wait for the message "Application startup complete"

**Mac/Linux:**
1. Open Terminal
2. Navigate to the folder: `cd ~/panago-validator`
3. Run: `docker compose up`

## Step 4: Open the Web Interface

Open your browser and go to: **http://localhost:8080**

You should see the Panago Price Validator interface.

## Using the Validator

### Run a Validation
1. Select the cities you want to validate
2. Click "Run Validation"
3. Wait for completion (progress bar will show status)
4. Download the Excel results

### Manage Cities (Admin)
1. Click "Admin" in the top-right corner
2. Add or remove cities/provinces as needed
3. Changes are saved automatically

## Stopping the Validator

- Close the terminal/command window, OR
- Press `Ctrl+C` in the terminal

## Troubleshooting

**"Docker is not running"**
- Open Docker Desktop and wait for it to start

**"Port 8080 already in use"**
- Close other applications using port 8080, OR
- Edit `docker-compose.yml` and change `8080:8080` to `9000:8080`, then use http://localhost:9000

**Browser shows "connection refused"**
- Wait a moment for the application to fully start
- Check the terminal for errors

## Need Help?

Contact your team lead for assistance.

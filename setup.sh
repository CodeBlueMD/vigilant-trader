#!/bin/bash
set -e

echo "Setting up VigilantTrader..."

# Create venv
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Copy env template if .env doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "Created .env from template. Edit it with your credentials before running."
fi

# Make launcher executable
if [ -f VigilantTrader.command ]; then
    chmod +x VigilantTrader.command
fi

echo ""
echo "Setup complete."
echo "  1. Edit .env with your SMTP credentials and Groq API key"
echo "  2. Run: source venv/bin/activate && python main.py"
echo "  3. Or double-click VigilantTrader.command on macOS"

#!/usr/bin/env bash
# IA Scenario Generator Setup
# Run this script to install and start Ollama for AI scenario generation

echo "🤖 Installing Ollama for AI Scenario Generation..."
echo ""

# Check if Ollama is already installed
if command -v ollama &> /dev/null; then
    echo "✓ Ollama is already installed"
else
    echo "📥 Installing Ollama..."
    curl -fsSL https://ollama.ai/install.sh | sh
    if [ $? -ne 0 ]; then
        echo "❌ Failed to install Ollama. Please install manually: https://ollama.ai"
        exit 1
    fi
    echo "✓ Ollama installed successfully"
fi

echo ""
echo "📦 Downloading Mistral model (first run only)..."
echo "   This may take a few minutes..."
ollama pull mistral

echo ""
echo "✅ Setup complete!"
echo ""
echo "To use the AI Scenario Generator:"
echo "1. Start Ollama server in another terminal:"
echo "   $ ollama serve"
echo ""
echo "2. Then start the Tactical Scenario Maker:"
echo "   $ python3 app.py"
echo ""
echo "3. Open http://localhost:8080 and go to the '🤖 IA' tab"

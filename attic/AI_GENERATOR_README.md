# 🤖 AI Scenario Generator

## Quick Start

The Tactical Scenario Maker now includes an **AI-powered scenario generator** that creates complete tactical scenarios from natural language descriptions.

### Prerequisites

1. **Ollama** (free, local, no API keys)
   - Install: https://ollama.ai
   - Or run: `bash INSTALL_OLLAMA.sh` from this directory

### Setup (One-time)

```bash
# 1. Install Ollama (if not already done)
bash INSTALL_OLLAMA.sh

# This downloads the Mistral 7B model (~4GB)
```

### Usage

#### Step 1: Start Ollama Server

Open a terminal and run:
```bash
ollama serve
```

You'll see:
```
Listening on 127.0.0.1:11434 (HTTP)
```

**Leave this running** — it's the AI backend.

#### Step 2: Start the Application

In another terminal:
```bash
python3 app.py
```

Open `http://localhost:8080`

#### Step 3: Generate Scenarios

1. Click the **🤖 IA** tab
2. Write a scenario in natural language, for example:

   > "Two patrol drones monitor a coastal area. When an intruder is detected within 5km, one drone pursues while the other maintains surveillance. After interception or 2 hours, both return to base."

3. Click **✨ Générer le scénario**
4. Wait 30-60 seconds (first time may take longer)
5. Review the generated scenario and click **📥 Importer comme scénario**

The scenario appears in your **Scénarios** tab, ready to edit or launch.

---

## How It Works

### Generation Pipeline

```
Natural Language Description
         ↓
    Ollama LLM
  (Mistral 7B)
         ↓
  Structured JSON
  - Agents with roles & positions
  - Tasks & sub-tasks
  - HTN methods & preconditions
         ↓
    KB Enrichment
  (Adds missing tasks)
         ↓
   Ready-to-use Scenario
```

### What Gets Generated

✅ **Agents** — Names, roles, positions, models  
✅ **Tasks** — Primary mission + trigger tasks  
✅ **Methods** — HTN decomposition logic  
✅ **Preconditions** — State variables & conditions  
✅ **KB Updates** — New tasks auto-added to knowledge base  

### Features

- ⚡ Fast local execution (no cloud uploads)
- 🔒 Privacy — data stays on your machine
- 🆓 Completely free (Ollama is open-source)
- 🤝 Seamless KB enrichment
- ⚠️ Automatic validation & warnings

---

## Troubleshooting

### "Ollama not running"

```bash
Error: Ollama not running. Install: https://ollama.ai
Then: ollama serve
Then download a model: ollama pull mistral
```

**Fix:** Start Ollama in another terminal:
```bash
ollama serve
```

### "Model not found"

```bash
Error: model 'mistral' not found
```

**Fix:** Download the model:
```bash
ollama pull mistral
```

### Generation times out (>60 sec)

- First generation after Ollama start: **normal**, may take 1-2 min
- Subsequent generations: 30-60 sec typical
- If consistently > 2 min: reduce system load or try lighter model:
  ```bash
  ollama pull neural-chat  # smaller, faster
  ```

### Invalid JSON response

The generator tries multiple parsing strategies. If you see "JSON decode error":
- Ensure Ollama is running and responsive
- Try regenerating (may be a network blip)
- Check Ollama logs for server issues

---

## Configuration

### Change LLM Model

Edit `bdd/ai_scenario_generator.py`, function `_query_ollama()`:

```python
def _query_ollama(prompt: str, model: str = "mistral") -> str:
    # Change "mistral" to another model
    response = requests.post(
        OLLAMA_URL,
        json={"model": "neural-chat", ...}  # <-- here
```

Then download the model:
```bash
ollama pull neural-chat
```

### Available Models

| Model | Size | Speed | Quality |
|-------|------|-------|---------|
| mistral | 4.1GB | Fast | Excellent |
| neural-chat | 4.1GB | Fast | Good |
| llama2 | 3.8GB | Slower | Very good |
| dolphin-mixtral | 26GB | Very slow | Excellent (needs GPU) |

---

## Performance Tips

1. **Warm up Ollama** — First request after server start takes longer
2. **GPU Acceleration** — Install GPU drivers for 2-5x speedup (optional)
3. **Simpler Descriptions** — Shorter scenarios generate faster
4. **Cached Models** — Once downloaded, models load instantly from disk

---

## What's Being Generated

### Example Input

> "Two drones patrol. When intruder detected <5km, one intercepts while other watches. Return to base after 30min or interception."

### Example Output

```json
{
  "scenario": {
    "name": "two_drones_patrol_intercept",
    "agents": {
      "patrol_1": {
        "x": 45.5,
        "y": 32.1,
        "role": "patrol",
        "model": "drone",
        "velocity": 10,
        "base_pos": [45.5, 32.1]
      },
      "patrol_2": { ... },
      "intruder": {
        "x": 47.2,
        "y": 33.8,
        "role": "intruder",
        ...
      }
    },
    "mission": ["patrouiller", "detect_et_intercepter"],
    "triggers": [...]
  },
  "warnings": [],
  "issues": {
    "missing_tasks": []
  }
}
```

---

## Advanced: KB Enrichment

When the AI generates a new task (e.g., "coordinated_intercept"), it:

1. ✅ Adds the task to `knowledge_base.json`
2. ✅ Creates HTN methods automatically
3. ✅ Adds preconditions based on context
4. ✅ Links to existing leaf tasks

You can then manually refine these in the **Connaissances HTN** tab.

---

## Privacy & Performance

- **No internet connection** — Works fully offline
- **No API calls** — All processing local
- **No data collection** — Nothing sent anywhere
- **Fast** — Mistral 7B is optimized for speed
- **Deterministic** — Same input often gives similar (not identical) outputs

---

## Contributing Improvements

To improve generation quality:

1. Refine the prompt in `ai_scenario_generator.py` (`_parse_scenario_from_description()`)
2. Add more examples to prompt engineering
3. Test with complex scenarios
4. Report issues or suggest better prompts

---

## License

Ollama: LLAMA 2 Community License  
Mistral Model: Apache 2.0  
Tactical Scenario Maker: Your use case license

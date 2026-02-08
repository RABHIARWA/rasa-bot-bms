# rasa-bot-bms

A conversational AI assistant built using Rasa CALM embedded within a web-based BMS platform (Business Management System).

## Prerequisites

- Python 3.11
- uv (Python package installer)
- Rasa Pro license key
- OpenAI API key

## Setup Instructions

### 1. Clone the Repository
```bash
git clone <repository-url>
cd rasa-bot-bms
```

### 2. Set Environment Variables
```bash
export RASA_PRO_LICENSE="your-rasa-pro-license-key"
export OPENAI_API_KEY="your-openai-api-key"
```

### 3. Create Virtual Environment
```bash
uv venv --python 3.11
```

### 4. Activate Virtual Environment
```bash
source .venv/bin/activate
```

### 5. Install Rasa Pro
```bash
pip install rasa-pro
```

### 6. Train the Model
```bash
rasa train
```

## Running the Bot

### Interactive Testing
```bash
rasa inspect
```

### Production Mode

Run both servers in separate terminals:

**Terminal 1 - Rasa Server:**
```bash
rasa run --enable-api --cors "*" --debug
```

**Terminal 2 - Custom Actions Server:**
```bash
rasa run actions
```

## API Endpoints

Once running, the Rasa server will be available at:
- Rasa API: `http://localhost:5005`
- Actions Server: `http://localhost:5055`

## Development

After making changes to training data or code:

1. Retrain the model: `rasa train`
2. Test your changes: `rasa inspect` or `rasa shell`

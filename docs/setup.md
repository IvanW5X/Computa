<!-- Condensed installation: clone, cp .env.example, Node deps, Ollama+Nemotron-mini, NVIDIA NIM creds, intent verification, warmup/health scripts. -->
# Setup
 
## Prerequisites
- Node.js 20+
- Python 3.11+
- Git
## Install
 
**Clone the repo and install Node dependencies:**
```bash
git clone <repo-url>
cd Computa
npm install
```
 
**Create a Python virtual environment and install dependencies:**
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
 
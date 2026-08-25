#!/usr/bin/env python3
"""Flask dashboard for the job agent - with first-run setup wizard."""

import asyncio
import json
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_cors import CORS
from werkzeug.utils import secure_filename

from agent_web import AgentWebRunner, AgentStatus, get_agent_runner
from config import AppConfig

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")
CORS(app)

# Global agent runner instance
_runner: Optional[AgentWebRunner] = None

def get_runner() -> AgentWebRunner:
    """Get or create the global agent runner."""
    global _runner
    if _runner is None:
        _runner = AgentWebRunner()
    return _runner

def is_first_run() -> bool:
    """Check if the user has not yet configured all required credentials."""
    try:
        cfg = AppConfig.from_env()
        # Check required fields: username, password, and at least one security Q/A
        required = [
            cfg.erp_username,
            cfg.erp_password,
            cfg.erp_security_answers,
            cfg.gmail_credentials_file,
            cfg.gmail_token_file,
            cfg.erp_jobs_url,
        ]
        # Check that security answers dict is not empty
        if not cfg.erp_security_answers:
            return True
        # Check that gmail credentials file exists (if not, might need setup)
        if not Path(cfg.gmail_credentials_file).exists():
            return True
        return False
    except Exception:
        return True

@app.route("/")
def index():
    """Dashboard home page - redirect to setup if first run."""
    if is_first_run():
        return redirect(url_for("setup"))
    return render_template("index.html")

@app.route("/setup", methods=["GET", "POST"])
def setup():
    """First-run setup wizard - only accessible before configuration."""
    if request.method == "POST":
        # Save all form fields to .env
        data = request.form.to_dict()
        # Convert checkboxes
        bool_keys = ["require_approval", "headless"]
        for key in bool_keys:
            data[key] = "true" if key in data else "false"

        # Write to .env
        env_path = Path(".env")
        if not env_path.exists():
            env_path = Path("../.env")
        if not env_path.exists():
            # Create new .env from scratch
            env_path = Path(".env")
            env_path.touch()

        # Read existing .env (if any) and update
        if env_path.exists():
            with open(env_path, "r") as f:
                lines = f.readlines()
        else:
            lines = []

        # Keep track of which keys we updated
        updated_keys = set()
        new_lines = []
        for line in lines:
            if line.strip().startswith("#") or not line.strip():
                new_lines.append(line)
                continue
            key = line.split("=")[0].strip()
            if key in data:
                # Also handle multi-line values? Not needed.
                new_lines.append(f"{key}={data[key]}\n")
                updated_keys.add(key)
            else:
                new_lines.append(line)

        # Add missing keys
        for key, value in data.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")

        with open(env_path, "w") as f:
            f.writelines(new_lines)

        flash("Configuration saved! You can now use the dashboard.", "success")
        return redirect(url_for("index"))

    # GET: show setup form with current .env values (or empty)
    env_vars = {}
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    key, value = line.strip().split("=", 1)
                    env_vars[key] = value
    # Defaults
    defaults = {
        "erp_username": "",
        "erp_password": "",
        "erp_security_q1": "",
        "erp_security_a1": "",
        "erp_security_q2": "",
        "erp_security_a2": "",
        "erp_security_q3": "",
        "erp_security_a3": "",
        "erp_otp_sender": "erpkgp@adm.iitkgp.ac.in",
        "erp_jobs_url": "",
        "llm_model": "gpt-4o-mini",
        "resume_file": "resume.txt",
        "gmail_credentials_file": "credentials.json",
        "gmail_token_file": "token.json",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": "465",
        "smtp_user": "",
        "smtp_password": "",
        "notify_email_to": "",
        "twilio_account_sid": "",
        "twilio_auth_token": "",
        "twilio_whatsapp_from": "whatsapp:+14155238886",
        "notify_whatsapp_to": "",
        "require_approval": "true",
        "headless": "false",
    }
    for key, default in defaults.items():
        env_vars.setdefault(key, default)

    return render_template("setup.html", env=env_vars)

@app.route("/settings", methods=["GET"])
def settings_page():
    """Settings page (only accessible after setup)."""
    if is_first_run():
        return redirect(url_for("setup"))
    return render_template("settings.html")

@app.route("/api/status", methods=["GET"])
def api_status():
    """Get the current agent status."""
    runner = get_runner()
    status = runner.get_status()
    return jsonify(status)

@app.route("/api/run", methods=["POST"])
def api_run():
    """Start the agent run."""
    runner = get_runner()
    if runner.status in (AgentStatus.RUNNING, AgentStatus.AWAITING_APPROVAL):
        return jsonify({"error": f"Agent is already {runner.status.value}"}), 409

    # Get config from request or use .env
    data = request.get_json() or {}
    config_override = data.get("config", {})

    # Start the agent in a background thread
    def run_agent():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(runner.run(config_override))
        except Exception as e:
            runner.status = AgentStatus.ERROR
            runner.error = str(e)
        finally:
            loop.close()

    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()

    return jsonify({"status": "started", "message": "Agent started"})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Stop the agent run (if possible)."""
    runner = get_runner()
    if runner.status in (AgentStatus.RUNNING, AgentStatus.AWAITING_APPROVAL):
        runner.stop_requested = True
        return jsonify({"status": "stopping", "message": "Stop requested"})
    return jsonify({"error": "Agent is not running"}), 409

@app.route("/api/approvals", methods=["GET"])
def api_approvals():
    """Get jobs awaiting approval."""
    runner = get_runner()
    approvals = runner.get_approvals()
    return jsonify(approvals)

@app.route("/api/approve", methods=["POST"])
def api_approve():
    """Approve a specific job."""
    data = request.get_json()
    if not data or "job_id" not in data:
        return jsonify({"error": "Missing job_id"}), 400

    runner = get_runner()
    result = runner.approve_job(data["job_id"])
    return jsonify(result)

@app.route("/api/reject", methods=["POST"])
def api_reject():
    """Reject a specific job."""
    data = request.get_json()
    if not data or "job_id" not in data:
        return jsonify({"error": "Missing job_id"}), 400

    runner = get_runner()
    result = runner.reject_job(data["job_id"])
    return jsonify(result)

@app.route("/api/apply", methods=["POST"])
def api_apply():
    """Apply to all approved jobs and continue."""
    runner = get_runner()
    if runner.status != AgentStatus.AWAITING_APPROVAL:
        return jsonify({"error": f"Agent is not awaiting approval (status: {runner.status.value})"}), 409

    # Run apply in background
    def do_apply():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(runner.apply_and_finish())
        except Exception as e:
            runner.status = AgentStatus.ERROR
            runner.error = str(e)
        finally:
            loop.close()

    thread = threading.Thread(target=do_apply, daemon=True)
    thread.start()

    return jsonify({"status": "applying", "message": "Applications in progress"})

@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Reset the agent state."""
    global _runner
    _runner = AgentWebRunner()
    return jsonify({"status": "reset"})

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    """Get current configuration (safe subset)."""
    try:
        cfg = AppConfig.from_env()
        # Return all fields except password and secret answers for security
        settings = {
            "erp_username": cfg.erp_username,
            "erp_jobs_url": cfg.erp_jobs_url,
            "llm_model": cfg.llm_model,
            "resume_file": cfg.resume_file,
            "require_approval": cfg.require_approval,
            "headless": cfg.headless,
            "notify_email_to": cfg.notify_email_to,
            "notify_whatsapp_to": cfg.notify_whatsapp_to,
            "gmail_credentials_file": cfg.gmail_credentials_file,
            "gmail_token_file": cfg.gmail_token_file,
            "erp_otp_sender": cfg.erp_otp_sender,
            "smtp_host": cfg.smtp_host,
            "smtp_port": cfg.smtp_port,
            "smtp_user": cfg.smtp_user,
            "twilio_account_sid": cfg.twilio_account_sid[:8] + "..." if cfg.twilio_account_sid else "",
            "twilio_whatsapp_from": cfg.twilio_whatsapp_from,
            "erp_security_answers_count": len(cfg.erp_security_answers),
            # Also include file existence flags
            "gmail_credentials_exists": Path(cfg.gmail_credentials_file).exists(),
            "gmail_token_exists": Path(cfg.gmail_token_file).exists(),
            "resume_exists": Path(cfg.resume_file).exists(),
        }
        return jsonify(settings)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    """Update configuration (write to .env file) - used by settings page."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing data"}), 400

    # Update .env file
    env_path = Path(".env")
    if not env_path.exists():
        env_path = Path("../.env")
    if not env_path.exists():
        return jsonify({"error": ".env file not found"}), 404

    # Read current .env
    with open(env_path, "r") as f:
        lines = f.readlines()

    # Update values
    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("#") or not line.strip():
            new_lines.append(line)
            continue
        key = line.split("=")[0].strip()
        if key in data:
            new_lines.append(f"{key}={data[key]}\n")
            updated = True
        else:
            new_lines.append(line)

    # Add missing keys
    for key, value in data.items():
        if not any(l.startswith(f"{key}=") for l in new_lines if not l.strip().startswith("#")):
            new_lines.append(f"{key}={value}\n")
            updated = True

    if updated:
        with open(env_path, "w") as f:
            f.writelines(new_lines)

    return jsonify({"status": "updated", "message": "Settings updated"})

@app.route("/api/logs", methods=["GET"])
def api_logs():
    """Get recent logs."""
    runner = get_runner()
    return jsonify({"logs": runner.get_logs()[-100:]})

@app.route("/api/gmail_instructions", methods=["GET"])
def api_gmail_instructions():
    """Return instructions for obtaining Gmail credentials.json."""
    instructions = {
        "steps": [
            "Go to Google Cloud Console (https://console.cloud.google.com/).",
            "Create a new project or select an existing one.",
            "Enable the Gmail API for your project.",
            "Create credentials (OAuth client ID) for a Desktop application.",
            "Download the JSON file and rename it to 'credentials.json'.",
            "Place it in the project root directory (same folder as this app).",
            "The first time you run the agent, it will open a browser for OAuth consent and generate token.json automatically."
        ],
        "more_info": "https://developers.google.com/gmail/api/quickstart/python"
    }
    return jsonify(instructions)

@app.route("/static/<path:path>")
def serve_static(path):
    """Serve static files."""
    return send_from_directory("static", path)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

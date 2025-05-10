# AI Assistant: A Telegram AI Chatbot for Task Management

## Overview

AI Assistant is a Telegram AI chatbot designed to streamline task management for students, professionals, and personal users. Built as part of a bachelor's thesis at ITPU / EPAM School of Digital Engineering, this project aims to reduce missed deadlines by integrating task management into a familiar messaging platform. AI Assistant allows users to create, list, mark done, and delete tasks using natural language, with reminders adjusted for their time zones. It leverages Python, the `python-telegram-bot` library, Google Gemini API for natural language understanding, `dateparser` for flexible date handling, and SQLite for a lightweight, user-friendly experience.

## Features

* **Natural Language Task Creation:** Add tasks with due dates using conversational language (e.g., "Remind me to Buy groceries tomorrow 3 PM").
* **Conversational Task Management:**
    * List tasks: "Show my tasks"
    * Mark tasks done: "Mark task 27 as done"
    * Delete tasks: "Delete task 15"
* **Command-Based Task Listing:** View all pending tasks with `/list`, showing interactive buttons for each task.
* **Inline Buttons:** Quickly mark tasks as "Done" or "Delete" them directly in the chat interface from the `/list` command output.
* **Time Zone Support:**
    * Set your personal timezone with `/set_timezone <Area/City>`.
    * View your current timezone with `/my_timezone`.
    * All task due dates and reminders are handled relative to your configured timezone.
* **Multi-Interval Reminders:** Receive reminders at configurable intervals (default: 24h, 12h, 6h, 3h, 1h, 15m, and when due) before a task’s deadline, adjusted to your local time.

## Prerequisites

Before setting up AI Assistant, ensure you have the following:

* Python 3.9 or higher installed (due to `zoneinfo` and modern type hinting).
* A Telegram account and a bot token from BotFather (see Telegram's official guide for creating a bot).
* A Google API Key with the Gemini API enabled. You can obtain this from [Google AI Studio](https://ai.google.dev/studio).
* A stable internet connection for the bot to interact with Telegram's and Google's APIs.

## Installation

1.  **Clone the Repository** (if applicable, or download the project files):
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Create and Activate a Virtual Environment** (Recommended):
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    AI Assistant relies on several Python libraries. Install them using pip:
    ```bash
    pip install -r requirements.txt
    ```
    *(Make sure your `requirements.txt` file includes `python-telegram-bot`, `python-dotenv`, `dateparser`, `google-generativeai`, and `tzdata` (for `zoneinfo` on some systems)).*

4.  **Set Up Your API Keys and Bot Token:**
    * Create a file named `.env` in the project root.
    * Add your Telegram bot token and Google API key:
        ```env
        TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here
        GOOGLE_API_KEY=your-google-api-key-here
        ```

5.  **Database Setup:**
    AI Assistant uses SQLite for task and user timezone storage. No additional setup is required; the database file (e.g., `tasks.db` as defined in `database.py`) will be created automatically in the project directory on the first run.

## Usage

1.  **Run the Bot:**
    Start the bot by running the main script from your project directory (ensure your virtual environment is active):
    ```bash
    python bot.py
    ```
    Ensure your terminal shows the bot is active (e.g., "Starting bot polling...") and listening for commands.

2.  **Interact with AI Assistant in Telegram:**
    * Open Telegram and search for your bot using its username (e.g., `@YourTaskBotName`).
    * Start the bot by sending the `/start` command to see a welcome message.
    * **Set your timezone first:** Use `/set_timezone Your/City` (e.g., `/set_timezone Asia/Tashkent`). You can check it with `/my_timezone`.
    * **Add tasks conversationally:**
        * `Remind me to submit the report by Friday 5pm`
        * `Need to buy groceries tomorrow morning`
        * `Call John next week`
        * `Book flights` (no date)
    * **List tasks conversationally:**
        * `Show my tasks`
        * `What's on my to-do list?`
    * **Mark tasks done conversationally** (use the ID shown in lists):
        * `Mark task 15 as done`
        * `Complete task 7`
    * **Delete tasks conversationally** (use the ID shown in lists):
        * `Delete task 12`
        * `Remove task 9`
    * **Use commands:**
        * `/list`: View all pending tasks with inline buttons for "Done" and "Delete".
        * `/help`: For a list of commands and guidance.

3.  **Receive Reminders:**
    AI Assistant will send reminders at specific intervals (24h, 12h, 6h, 3h, 1h, 15m, and at due time) before a task’s due date, adjusted to your set time zone. Make sure your Telegram notifications are enabled for the bot.

## Testing

*(If you have a `tests` directory and test files, describe them here. Example below assumes a `test_database.py` and `test_bot_handlers.py`)*

AI Assistant includes a test suite to ensure reliability:
```bash
pip install pytest pytest-mock # If not already in requirements.txt
pytest
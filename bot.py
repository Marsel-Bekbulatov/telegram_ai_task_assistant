# bot.py
import logging
import os
from datetime import datetime, timedelta, timezone
import zoneinfo
import sqlite3 
from dotenv import load_dotenv
import database
import dateparser 
import functools 

# --- Gemini Integration ---
try:
    import google.generativeai as genai
    google_ai_installed = True
except ImportError:
    google_ai_installed = False
# --- End Gemini Import ---

# Import Telegram libraries
from telegram import Update, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler
)
from telegram.constants import ParseMode
from telegram.error import BadRequest 

# Load environment variables
load_dotenv()

# --- Logging Configuration ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger('apscheduler.scheduler').setLevel(logging.INFO)
logging.getLogger('apscheduler.executors.default').setLevel(logging.INFO)
logging.getLogger('dateparser').setLevel(logging.WARNING)
if google_ai_installed:
    logging.getLogger('google.generativeai').setLevel(logging.INFO)
    logging.getLogger('google.api_core').setLevel(logging.INFO) 
logger = logging.getLogger(__name__)

# --- Constants ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") # Load Google API Key

if not TELEGRAM_BOT_TOKEN: logger.critical("FATAL ERROR: Telegram token missing!"); exit()

UTC = zoneinfo.ZoneInfo("UTC")

# Notification Intervals Definition
NOTIFICATION_INTERVALS = {
    'notified_24h': (timedelta(hours=24), "in less than 24 hours"),
    'notified_12h': (timedelta(hours=12), "in less than 12 hours"),
    'notified_6h':  (timedelta(hours=6), "in less than 6 hours"),
    'notified_3h':  (timedelta(hours=3), "in less than 3 hours"),
    'notified_1h':  (timedelta(hours=1), "in less than 1 hour"),
    'notified_15m': (timedelta(minutes=15), "in less than 15 minutes"),
    'notified_final_due': (timedelta(seconds=0), "NOW or is OVERDUE")
}

# --- Gemini Configuration (Refined) ---
gemini_model = None
gemini_configured = False 

if google_ai_installed and GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY) # Use genai 
        safety_settings_med = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
        gemini_model_name = "gemini-1.5-flash-latest"
        # initialize the model
        gemini_model = genai.GenerativeModel(
             model_name=gemini_model_name,
             safety_settings=safety_settings_med
             
        )
        gemini_configured = True 
        logger.info(f"Gemini configured successfully with model: {gemini_model_name}")
    except Exception as e:
        logger.error(f"Failed to configure Gemini API: {e}", exc_info=True)
    
elif not google_ai_installed:
     logger.warning("google-generativeai package not installed. Conversational features DISABLED.")
else: 
    logger.warning("Gemini API key not found in .env. Conversational features DISABLED.")


# --- Helper Functions ---
def get_user_tz(user_id: int) -> zoneinfo.ZoneInfo:
    tz_str = database.get_user_timezone_str(user_id);
    try:
        return zoneinfo.ZoneInfo(tz_str)
    except Exception:
        logger.warning(f"Bad TZ '{tz_str}' user {user_id}, use UTC.")
        return UTC

def format_datetime_local(dt_utc: datetime | None, user_tz: zoneinfo.ZoneInfo) -> str:
    if not dt_utc or not dt_utc.tzinfo: return "[No Date Set]" if dt_utc is None else "[Invalid Date (No TZ)]"
    try:
        local_dt = dt_utc.astimezone(user_tz)
        return local_dt.strftime('%Y-%m-%d %H:%M')
    except Exception as e:
        logger.error(f"Err format dt {dt_utc} to {user_tz}: {e}")
        return "[Date Error]"


def build_task_message_text(task_data, user_tz: zoneinfo.ZoneInfo) -> str:
    """Builds the standard text display for a task."""
    task_id = task_data['id']; description = task_data['description']; due_date_display = ""
    if task_data['due_date']:
        try:
            dt_utc_aware = datetime.fromisoformat(task_data['due_date']).replace(tzinfo=UTC)
            due_date_display = f" (Due: {format_datetime_local(dt_utc_aware, user_tz)})"
        except Exception as e:
            logger.error(f"Error parsing/converting date string '{task_data['due_date']}' for task {task_id} in build_text: {e}")
            due_date_display = " (Due: Error)"
    return f"📌 ID: {task_id} - {description}{due_date_display}"

def build_task_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Builds the standard action keyboard (Done, Delete) for a task."""

    return InlineKeyboardMarkup([[
         InlineKeyboardButton("✅ Done", callback_data=f"done:{task_id}"),
         InlineKeyboardButton("🗑️ Delete", callback_data=f"delete:{task_id}")
    ]])

# --- Gemini Function ---
def add_task_logic(description: str, due_date: str | None = None, user_id_for_task: int = 0, chat_id_for_task: int = 0) -> str:
    """Internal logic to add a task, parsing date string."""
    logger.info(f"FUNC CALL(logic): add_task: desc='{description}', due='{due_date}', u={user_id_for_task}, c={chat_id_for_task}")
    if not user_id_for_task or not chat_id_for_task:
        logger.error("add_task_logic missing context!")
        return "Error: Missing context."

    user_tz = get_user_tz(user_id_for_task)
    now_local = datetime.now(user_tz)
    due_date_utc = None
    if due_date:
        parser_settings = { 'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': now_local, 'TIMEZONE': str(user_tz.key), 'RETURN_AS_TIMEZONE_AWARE': True }
        try:
            parsed_dates = dateparser.parse(due_date, settings=parser_settings, languages=['en'])
            if parsed_dates:
                if parsed_dates.tzinfo is None:
                    logger.warning(f"dateparser naive dt '{parsed_dates}', localizing...")
                    due_date_local_aware = parsed_dates.replace(tzinfo=user_tz)
                else:
                    due_date_local_aware = parsed_dates.astimezone(user_tz)
                due_date_utc = due_date_local_aware.astimezone(UTC)
                logger.info(f"Parsed Gemini due '{due_date}' -> UTC: {due_date_utc}")
            else:
                logger.warning(f"dateparser failed parse: '{due_date}'")
        except Exception as e:
             logger.error(f"Error parsing date '{due_date}' via dateparser: {e}", exc_info=True)

    task_id = database.add_task(user_id_for_task, chat_id_for_task, description, due_date_utc)
    if task_id:
        response = f"Okay, I've added task '{description}' (ID: {task_id})."
        if due_date_utc:
            response += f" Due date is set to {format_datetime_local(due_date_utc, user_tz)}."
        elif due_date and not due_date_utc: 
             response += " I couldn't understand the due date, so none was set."
        elif not due_date:
             response += " No due date was set."
        return response
    else:
        return "Sorry, I failed to add the task to the database."

def list_tasks_logic(user_id_for_task: int = 0, status_filter: str = 'pending') -> str:
    """Internal logic to retrieve and format tasks for conversational reply."""
    logger.info(f"FUNC CALL(logic): list_tasks: u={user_id_for_task}, status={status_filter}")
    if not user_id_for_task: logger.error("list_tasks_logic missing user ID!"); return "Error: Missing context."

    user_tz = get_user_tz(user_id_for_task)
    try:
        tasks = database.get_user_tasks(user_id_for_task, status=status_filter)
    except Exception as e:
        logger.error(f"DB error getting tasks user {user_id_for_task}: {e}")
        return "Sorry, couldn't retrieve tasks due to a database error."

    if not tasks:
        return f"You have no {status_filter} tasks! 🎉"

    #  list of task 
    task_lines = []
    for task in tasks:
        task_lines.append(build_task_message_text(task, user_tz).replace("📌 ", "- ").replace("*", ""))

    formatted_list = "\n".join(task_lines)

    message = f"OK. Your {status_filter} tasks (Times in {user_tz.key}):\n\n{formatted_list}"
    return message

def mark_task_done_logic(task_id: int = 0, user_id_for_task: int = 0) -> str:
    """Internal logic to mark a task as done."""
    logger.info(f"FUNC CALL(logic): mark_task_done: id={task_id}, u={user_id_for_task}")
    if not user_id_for_task or not task_id: return "Error: Missing task ID or user context."

    task = database.get_task_by_id(task_id, user_id_for_task)
    if not task: return f"Sorry, I couldn't find task ID {task_id}."
    if task['status'] == 'done': return f"Task {task_id} ('{task['description']}') is already done."

    if database.update_task_status(task_id, user_id_for_task, status='done'):
        return f"✅ Marked task {task_id} ('{task['description']}') as done."
    else:
        return f"❌ Failed to mark task {task_id} as done (it might have been deleted)."

def delete_task_logic(task_id: int = 0, user_id_for_task: int = 0) -> str:
    """Internal logic to delete a task."""
    logger.info(f"FUNC CALL(logic): delete_task: id={task_id}, u={user_id_for_task}")
    if not user_id_for_task or not task_id: return "Error: Missing task ID or user context."

    task = database.get_task_by_id(task_id, user_id_for_task)
    desc = task['description'] if task else f"ID {task_id}"

    if database.delete_task(task_id, user_id_for_task):
        return f"🗑️ Deleted task {task_id} ('{desc}')."
    else:
        return f"❌ Failed to delete task {task_id}. It might have already been deleted."


# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user; user_id = user.id; logger.debug(f"/start from {user_id}")
    _ = database.get_user_timezone_str(user_id) 
    await update.message.reply_html(rf"Hi {user.mention_html()}! Use /help or tell me what task to add.")
    job_name = "global_deadline_check"; job_queue = context.application.job_queue
    try:
        current_jobs = job_queue.get_jobs_by_name(job_name)
        logger.info(f"Check jobs '{job_name}'. Found: {current_jobs}")
        if not current_jobs:
            logger.info(f"Scheduling job '{job_name}'...")
            try: job_queue.run_repeating(check_deadlines, interval=900, first=5, name=job_name); logger.info(f"Scheduled job '{job_name}'.")
            except Exception as e: logger.error(f"Fail schedule job '{job_name}': {e}")
        else: logger.info(f"Job '{job_name}' exists.")
    except Exception as e: logger.error(f"Error check/schedule job: {e}", exc_info=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #  help command 
    logger.debug("/help received")
    help_text = """
Here's what I can do:
* Add tasks naturally (e.g., "Remind me about X tomorrow").
* Ask me to list tasks (e.g., "show my tasks").
* Tell me to mark tasks done (e.g., "mark task 123 done").
* Tell me to delete tasks (e.g., "delete task 45").
* `/list` - Show pending tasks with Done/Delete buttons.
* `/set_timezone <Area/City>` - Set your timezone. List: <https://en.wikipedia.org/wiki/List_of_tz_database_time_zones>
* `/my_timezone` - Show your current timezone setting.
* `/help` - Show this message.
"""
    await update.message.reply_text(help_text, disable_web_page_preview=True)

async def set_timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    
    user_id = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /set_timezone <Area/City> ..."); return
    timezone_str = args[0]
    logger.debug(f"Set timezone '{timezone_str}' for {user_id}")
    is_valid = False
    try:
        zoneinfo.ZoneInfo(timezone_str)
        is_valid = True
    except Exception:
        pass
    if not is_valid:
        await update.message.reply_text(f"❌ Invalid timezone: '{timezone_str}' ..."); return
    if database.set_user_timezone(user_id, timezone_str):
        user_tz = get_user_tz(user_id)
        now_local = datetime.now(user_tz)
        await update.message.reply_text(f"✅ TZ set: {timezone_str}\nCurrent: {now_local.strftime('%Y-%m-%d %H:%M:%S %Z%z')}")
    else:
        await update.message.reply_text("❌ Failed to save timezone.")

async def my_timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    
    user_id = update.effective_user.id
    user_tz_str = database.get_user_timezone_str(user_id)
    user_tz = get_user_tz(user_id)
    now_local = datetime.now(user_tz)
    await update.message.reply_text(
        f"TZ: *{user_tz_str}*\nNow: {now_local.strftime('%Y-%m-%d %H:%M:%S %Z%z')}",
        parse_mode=ParseMode.MARKDOWN
    )



async def list_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists pending tasks with inline action buttons."""

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_tz = get_user_tz(user_id)
    logger.debug(f"/list user {user_id} TZ:{user_tz.key}")
    try:
        tasks = database.get_user_tasks(user_id, status='pending')
    except Exception as e:
        logger.error(f"Failed get tasks user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Sorry, error retrieving tasks.")
        return
    if not tasks:
        await update.message.reply_text("No pending tasks! 🎉")
        return

    await update.message.reply_text(f"Pending tasks (Times: {user_tz.key}):")
    max_show=20
    shown=0
    for task in tasks:
        if shown >= max_show:
            await context.bot.send_message(chat_id=chat_id, text=f"...\n(First {max_show})")
            break
        task_id = task['id']
        try:
            
            msg_text = build_task_message_text(task, user_tz)
        except Exception as e:
            logger.error(f"Err build text task {task_id}: {e}")
            msg_text = f"⚠️ Error display task {task_id}."
        
        keyboard = build_task_keyboard(task_id)
        try:
            await context.bot.send_message(
                 chat_id=chat_id,
                 text=msg_text,
                 reply_markup=keyboard,
                 parse_mode=ParseMode.MARKDOWN 
            )
            shown += 1
        except Exception as e:
            logger.error(f"Fail send task {task_id}: {e}")

async def done_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    
    user_id = update.effective_user.id
    args = context.args
    logger.debug(f"/done args: {args}")
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /done <id>")
        return
    task_id = int(args[0])
    task = database.get_task_by_id(task_id, user_id)
    if not task:
        await update.message.reply_text(f"ID {task_id} NF.")
        return
    if task['status'] == 'done':
        await update.message.reply_text(f"ID {task_id} done.")
        return
    if database.update_task_status(task_id, user_id, status='done'):
        await update.message.reply_text(f"✅ Marked {task_id} done.")
    else:
        await update.message.reply_text(f"❌ Fail mark {task_id} done.")

async def delete_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    
    user_id = update.effective_user.id
    args = context.args
    logger.debug(f"/delete args: {args}")
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /delete <id>")
        return
    task_id = int(args[0])
    task_del = database.get_task_by_id(task_id, user_id)
    if not task_del:
        await update.message.reply_text(f"ID {task_id} NF.")
        return
    if database.delete_task(task_id, user_id):
        await update.message.reply_text(f"🗑️ Deleted {task_id}.")
    else:
        await update.message.reply_text(f"❌ Fail delete {task_id}.")

# --- Callback Query Handler ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button clicks for Done/Delete."""
    
    query = update.callback_query
    user_id = query.from_user.id
    user_tz = get_user_tz(user_id)

    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Fail answer cb: {e}")

    callback_data = query.data
    logger.debug(f"CB: Data='{callback_data}' User={user_id} TZ={user_tz.key}")

    try:
        action, task_id_str = callback_data.split(":", 1)
        task_id = int(task_id_str)
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid CB data format: '{callback_data}'. {e}")
        try: await query.edit_message_text("⚠️ Error.")
        except BadRequest: pass
        return
    except Exception as e:
         logger.error(f"Unexpected error parsing CB data '{callback_data}'. {e}")
         try: await query.edit_message_text("⚠️ Error.")
         except BadRequest: pass
         return

    task = database.get_task_by_id(task_id, user_id)
    if not task:
        try: await query.edit_message_text(f"Task {task_id} NF.", reply_markup=None)
        except BadRequest: pass
        return

    original_display_text = build_task_message_text(task, user_tz) 

    if action == "done":
        logger.info(f"Mark {tid} done user {uid}") 
        logger.info(f"Mark task {task_id} done user {user_id}")
        if task['status']=='done':
            logger.info(f"Task {task_id} already done.")
            done_txt=f"✅ Done!\n~{original_display_text}~"
            try:
                await query.edit_message_text(text=done_txt,parse_mode=ParseMode.MARKDOWN,reply_markup=None)
            except BadRequest:
                 logger.debug(f"Msg task {task_id} done state no change.")
            except Exception as e:
                 logger.error(f"Err edit msg done task {task_id}: {e}")
            return 

        if database.update_task_status(task_id, user_id, status='done'):
            logger.info(f"OK mark {task_id} done.")
            new_txt=f"✅ DONE: ~{original_display_text}~"
            try:
                await query.edit_message_text(new_txt, parse_mode=ParseMode.MARKDOWN, reply_markup=None)
            except BadRequest as e:
                logger.warning(f"Edit fail (done cb):{e}")
        else:
            logger.warning(f"Fail mark {task_id} DB")
            try:
                await query.edit_message_text(f"⚠️ Fail mark {task_id}.",reply_markup=None)
            except BadRequest: pass 

    elif action=="delete":
        logger.info(f"Delete task {task_id} user {user_id}")
        if database.delete_task(task_id, user_id):
            logger.info(f"OK delete {task_id}.")
            new_txt=f"🗑️ Deleted: ~{original_display_text}~"
            try:
                await query.edit_message_text(new_txt, parse_mode=ParseMode.MARKDOWN, reply_markup=None)
            except BadRequest as e:
                logger.warning(f"Edit fail (del cb):{e}")
        else:
            logger.warning(f"Fail delete {task_id} DB")
            try:
                await query.edit_message_text(f"⚠️ Fail delete {task_id}.",reply_markup=None)
            except BadRequest: pass
    else:
        logger.warning(f"Unknown CB action:'{action}'")
        try:
            await query.edit_message_text("⚠️ Unknown.",reply_markup=None)
        except BadRequest: pass

# --- Conversational Handler using Gemini ---
async def handle_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles general text using Gemini, supporting multiple task actions."""
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_text = update.message.text
    logger.debug(f"handle_conversation user {user_id}: '{user_text[:100]}...'")

    if not gemini_configured or not gemini_model:
        logger.warning("Gemini skip conv."); return

    # --- Gemini Callables ---
    def add_task_wrapper(description: str, due_date: str | None = None):
        """Adds task. Extracts description & optional due date string."""
        return add_task_logic(description=description, due_date=due_date, user_id_for_task=user_id, chat_id_for_task=chat_id)

    def list_tasks_wrapper(status_filter: str = 'pending'):
        """Lists tasks, optionally filtering by status (pending or done)."""
        status = status_filter if status_filter in ['pending', 'done'] else 'pending'
        return list_tasks_logic(user_id_for_task=user_id, status_filter=status)

    def mark_task_done_wrapper(task_id: int):
        """Marks a specific task ID as done."""
        return mark_task_done_logic(task_id=task_id, user_id_for_task=user_id)

    def delete_task_wrapper(task_id: int):
        """Deletes a specific task ID."""
        return delete_task_logic(task_id=task_id, user_id_for_task=user_id)

    tools_for_gemini = [ add_task_wrapper, list_tasks_wrapper, mark_task_done_wrapper, delete_task_wrapper ]

    try:
        model_with_tools = genai.GenerativeModel(
             model_name=gemini_model_name, safety_settings=safety_settings_med, tools=tools_for_gemini
        )
        chat = model_with_tools.start_chat(enable_automatic_function_calling=True)
        await update.message.reply_chat_action("typing")
        response = await chat.send_message_async(user_text)
        reply_text = response.text
        logger.info(f"Gemini final response user {user_id}: '{reply_text}'")

        if reply_text:
            await update.message.reply_text(reply_text)
        else:
            logger.info(f"Gemini func call complete user {user_id}, no final text.")
            

    except Exception as e:
        logger.error(f"Error Gemini conv/func call user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Sorry, AI brain error.")


# --- Notification Job ---
async def check_deadlines(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Checks tasks, comparing in UTC, displaying notifications in user's local time."""
    
    logger.debug("--- Entering check_deadlines ---")
    now_utc = datetime.now(UTC)
    logger.info(f"Run check @ {now_utc}(UTC)")
    try:
        tasks = database.get_pending_tasks_with_due_dates()
        logger.debug(f"Got {len(tasks) if tasks else 0} tasks.")
    except Exception as e:
        logger.error(f"Failed retrieve tasks: {e}", exc_info=True)
        return
    if not tasks:
        logger.info("No pending tasks.")
        return

    logger.info(f"Checking {len(tasks)} tasks.")
    for task in tasks:
        tid=task['id']; cid=task['chat_id']; desc=task['description']; tz_str=task['user_timezone']; tz=UTC
        try:
            tz = zoneinfo.ZoneInfo(tz_str)
        except Exception:
            logger.warning(f"Task {tid}: Invalid TZ '{tz_str}'. Use UTC.")

        try:
            due_str = task['due_date']
            if not due_str: continue

            due_utc = datetime.fromisoformat(due_str).replace(tzinfo=UTC)
            remain = due_utc - now_utc

            final_key = 'notified_final_due'
            if remain <= timedelta(seconds=0):
                if not task[final_key]:
                    logger.debug(f"Task {tid} DUE/OVERDUE. Send final.")
                    i_desc = NOTIFICATION_INTERVALS[final_key][1]
                    d_loc = format_datetime_local(due_utc, tz)
                    msg = f"🔔 DUE {i_desc}!\nID:{tid}\nDesc:{desc}\nDue:{d_loc}({tz.key})"
                    try:
                        await context.bot.send_message(cid,msg)
                        logger.info(f"Sent '{i_desc}' for {tid}")
                        database.mark_specific_notification_sent(tid, final_key)
                    except Exception as e:
                         logger.error(f"Fail send final for {tid}: {e}", exc_info=True)
            
                continue 

            sorted_intervals = sorted([(k,v) for k,v in NOTIFICATION_INTERVALS.items() if k!=final_key], key=lambda i:i[1][0])
            
            for int_key, (int_delta, int_desc) in sorted_intervals:
                if remain <= int_delta and not task[int_key]:
                    logger.debug(f"Task {tid}: MET {int_key}. Send.")
                    d_loc=format_datetime_local(due_utc, tz)
                    msg = f"⏳ Reminder: Due {int_desc}!\nID:{tid}\nDesc:{desc}\nDue:{d_loc}({tz.key})"
                    try:
                        await context.bot.send_message(cid, msg)
                        logger.info(f"Sent '{int_desc}' for {tid}")
                        
                        if database.mark_specific_notification_sent(tid, int_key):
                            logger.debug(f"Task {tid}: Marked {int_key}. Break.")
                        else:
                            logger.error(f"Task {tid}: Failed mark {int_key}. Break anyway.")
                    except Exception as e:
                        logger.error(f"Fail send '{int_desc}' for {tid}: {e}", exc_info=True)
                        logger.debug(f"Task {tid}: Break on send error.")
                    
                    break
        except (ValueError, TypeError) as e:
             logger.error(f"Error task {tid}: Parse/TZ error. {e}", exc_info=True)
        except Exception as e:
             logger.error(f"Unexpected error task {tid}: {e}", exc_info=True)
    logger.debug("--- Exit check_deadlines ---")


# --- Main Setup ---
async def post_init(application: Application) -> None:
    
    logger.debug("Running post_init...")
    database.init_db()
    logger.info("DB init called.")
    try:
        await application.bot.set_my_commands([
            BotCommand("start", "Start"), BotCommand("help", "Help"),
            BotCommand("list", "List tasks"), BotCommand("set_timezone", "Set timezone"),
            BotCommand("my_timezone", "Show timezone"),
        ])
        logger.info("Commands set.")
    except Exception as e:
        logger.error(f"Set commands fail: {e}")

def main() -> None:
    """Starts the bot with expanded Gemini conversation handler."""
    
    logger.info("Starting main function...")
    logger.debug("Building application (no persistence)...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    logger.debug("Adding command handlers...")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_tasks_command))
    application.add_handler(CommandHandler("done", done_task_command))
    application.add_handler(CommandHandler("delete", delete_task_command))
    application.add_handler(CommandHandler("set_timezone", set_timezone_command))
    application.add_handler(CommandHandler("my_timezone", my_timezone_command))

    logger.debug("Adding CallbackQueryHandler...")
    application.add_handler(CallbackQueryHandler(button_callback))

    if gemini_configured:
        logger.info("Gemini configured, adding conversational handler.")
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_conversation))
    else:
        logger.warning("Gemini not configured, conversational handler DISABLED.")

    logger.info("Starting bot polling...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
         logger.critical(f"Polling failed: {e}", exc_info=True)

if __name__ == "__main__":
    # Dependency Checks
    if not google_ai_installed: logger.critical("FATAL: google-generativeai missing."); exit()
    try: import dateparser; logger.info("dateparser found.")
    except ImportError: logger.critical("FATAL: dateparser missing."); exit()
    try: import tzdata; logger.info("tzdata found.")
    except ImportError: logger.warning("tzdata not found.")
    try: import sqlite3; logger.info("sqlite3 loaded.")
    except ImportError: logger.error("sqlite3 failed import.")
    main()
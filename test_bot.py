import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
import zoneinfo
import sqlite3
from telegram import Update, User, Chat, Message, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes
from telegram.constants import ParseMode
import bot
import database

# Pytest-asyncio configuration
pytestmark = pytest.mark.asyncio

# Fixtures
@pytest.fixture
def mock_update():
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User, id=12345)
    update.effective_chat = MagicMock(spec=Chat, id=67890)
    update.message = MagicMock(spec=Message)
    return update

@pytest.fixture
def mock_context():
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.application = MagicMock(spec=Application)
    context.bot = AsyncMock()
    context.application.job_queue = MagicMock()
    return context

@pytest.fixture
def mock_db(mocker):
    mocker.patch('sqlite3.connect', return_value=MagicMock())
    conn = sqlite3.connect.return_value
    conn.cursor.return_value = MagicMock()
    return conn

# Unit Tests
async def test_get_user_tz(mocker):
    mocker.patch('database.get_user_timezone_str', return_value='Asia/Tashkent')
    user_tz = bot.get_user_tz(12345)
    assert isinstance(user_tz, zoneinfo.ZoneInfo)
    assert str(user_tz) == 'Asia/Tashkent'

async def test_format_datetime_local():
    dt_utc = datetime(2025, 5, 10, 12, 0, tzinfo=zoneinfo.ZoneInfo('UTC'))
    user_tz = zoneinfo.ZoneInfo('Asia/Tashkent')
    result = bot.format_datetime_local(dt_utc, user_tz)
    assert result == '2025-05-10 17:00'

async def test_add_task_logic(mocker):
    mocker.patch('database.get_user_timezone_str', return_value='Asia/Tashkent')
    mocker.patch('database.add_task', return_value=1)
    mocker.patch('dateparser.parse', return_value=datetime(2025, 5, 10, 17, 0, tzinfo=zoneinfo.ZoneInfo('Asia/Tashkent')))
    result = bot.add_task_logic(
        description='Submit thesis',
        due_date='May 10, 2025, 5 PM',
        user_id_for_task=12345,
        chat_id_for_task=67890
    )
    assert result == "Okay, I've added task 'Submit thesis' (ID: 1). Due date is set to 2025-05-10 17:00."

async def test_list_tasks_logic(mocker):
    mocker.patch('database.get_user_timezone_str', return_value='Asia/Tashkent')
    mocker.patch('database.get_user_tasks', return_value=[
        {'id': 1, 'description': 'Submit thesis', 'due_date': '2025-05-10T12:00:00+00:00', 'status': 'pending'}
    ])
    result = bot.list_tasks_logic(user_id_for_task=12345, status_filter='pending')
    assert 'ID: 1 - Submit thesis (Due: 2025-05-10 17:00)' in result

async def test_mark_task_done_logic(mocker):
    mocker.patch('database.get_task_by_id', return_value={'id': 1, 'description': 'Submit thesis', 'status': 'pending'})
    mocker.patch('database.update_task_status', return_value=True)
    result = bot.mark_task_done_logic(task_id=1, user_id_for_task=12345)
    assert result == "✅ Marked task 1 ('Submit thesis') as done."

async def test_delete_task_logic(mocker):
    mocker.patch('database.get_task_by_id', return_value={'id': 1, 'description': 'Submit thesis'})
    mocker.patch('database.delete_task', return_value=True)
    result = bot.delete_task_logic(task_id=1, user_id_for_task=12345)
    assert result == "🗑️ Deleted task 1 ('Submit thesis')."

# Functional Tests
async def test_start_command(mock_update, mock_context):
    await bot.start(mock_update, mock_context)
    mock_update.message.reply_html.assert_called_with(
        f"Hi {mock_update.effective_user.mention_html()}! Use /help or tell me what task to add."
    )

async def test_list_tasks_command(mock_update, mock_context, mocker):
    mocker.patch('database.get_user_timezone_str', return_value='Asia/Tashkent')
    mocker.patch('database.get_user_tasks', return_value=[
        {'id': 1, 'description': 'Submit thesis', 'due_date': '2025-05-10T12:00:00+00:00', 'status': 'pending'}
    ])
    await bot.list_tasks_command(mock_update, mock_context)
    mock_context.bot.send_message.assert_called()
    call_args = mock_context.bot.send_message.call_args
    assert 'ID: 1 - Submit thesis (Due: 2025-05-10 17:00)' in call_args[1]['text']
    assert isinstance(call_args[1]['reply_markup'], InlineKeyboardMarkup)

async def test_check_deadlines(mock_context, mocker):
    task = {
        'id': 1, 'chat_id': 67890, 'description': 'Submit thesis',
        'due_date': (datetime.now(zoneinfo.ZoneInfo('UTC')) + timedelta(minutes=10)).isoformat(),
        'user_timezone': 'Asia/Tashkent',
        'notified_24h': False, 'notified_12h': False, 'notified_6h': False,
        'notified_3h': False, 'notified_1h': False, 'notified_15m': False,
        'notified_final_due': False
    }
    mocker.patch('database.get_pending_tasks_with_due_dates', return_value=[task])
    mocker.patch('database.mark_specific_notification_sent', return_value=True)
    await bot.check_deadlines(mock_context)
    assert mock_context.bot.send_message.called, f"send_message was not called. Mock calls: {mock_context.bot.send_message.mock_calls}"
    call_args = mock_context.bot.send_message.call_args
    assert call_args is not None, "call_args is None"
    print(f"send_message call args: {call_args}")
    assert call_args[0][0] == 67890, f"Expected chat_id 67890, got {call_args[0][0]}"
    expected_text = '⏳ Reminder: Due in less than 15 minutes!\nID:1\nDesc:Submit thesis'
    assert expected_text in call_args[0][1], f"Expected message '{expected_text}' not found in: {call_args[0][1]}"

async def test_button_callback_done(mock_update, mock_context, mocker):
    mocker.patch('database.get_user_timezone_str', return_value='Asia/Tashkent')
    mocker.patch('database.get_task_by_id', return_value={
        'id': 1, 'description': 'Submit thesis', 'due_date': '2025-05-10T12:00:00+00:00', 'status': 'pending'
    })
    mocker.patch('database.update_task_status', return_value=True)
    mock_update.callback_query = MagicMock(data='done:1', from_user=MagicMock(id=12345))
    mock_update.callback_query.answer = AsyncMock()
    mock_update.callback_query.edit_message_text = AsyncMock()
    await bot.button_callback(mock_update, mock_context)
    assert mock_update.callback_query.edit_message_text.called, f"edit_message_text was not called. Call args: {mock_update.callback_query.edit_message_text.call_args}"
    call_args = mock_update.callback_query.edit_message_text.call_args
    assert call_args is not None, "call_args is None"
    print(f"edit_message_text call args: {call_args}")
    expected_text = '✅ DONE: ~📌 ID: 1 - Submit thesis (Due: 2025-05-10 17:00)~'
    assert expected_text in call_args[0][0], f"Expected message '{expected_text}' not found in: {call_args[0][0]}"
    assert call_args[1]['parse_mode'] == ParseMode.MARKDOWN, f"Expected parse_mode MARKDOWN, got {call_args[1]['parse_mode']}"
    assert call_args[1]['reply_markup'] is None, f"Expected reply_markup None, got {call_args[1]['reply_markup']}"

async def test_button_callback_invalid_data(mock_update, mock_context, mocker):
    mocker.patch('database.get_user_timezone_str', return_value='Asia/Tashkent')
    mock_update.callback_query = MagicMock(data=None, from_user=MagicMock(id=12345))
    mock_update.callback_query.answer = AsyncMock()
    mock_update.callback_query.edit_message_text = AsyncMock()
    await bot.button_callback(mock_update, mock_context)
    assert mock_update.callback_query.edit_message_text.called, f"edit_message_text was not called. Call args: {mock_update.callback_query.edit_message_text.call_args}"
    call_args = mock_update.callback_query.edit_message_text.call_args
    assert call_args is not None
    assert '⚠️ Error.' in call_args[0][0], f"Expected error message, got: {call_args[0][0]}"
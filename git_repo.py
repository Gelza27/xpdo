import os
import base64
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

# Conversation states
(
    AUTHENTICATED, GET_REPO_NAME, GET_FILE,
    SELECT_REPO, REPO_ACTION, SELECT_FILE_UPDATE,
    GET_UPDATE_FILE, SELECT_FILE_DELETE,
    DELETE_REPO, CONFIRM_DELETE_REPO
) = range(10)

PAGE_SIZE = 10  # Number of repos per page

async def fetch_user_repos(token, page=1):
    headers = {'Authorization': f'token {token}'}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f'https://api.github.com/user/repos?per_page={PAGE_SIZE}&page={page}',
            headers=headers
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()

async def get_file_sha(token, owner, repo, file_path):
    headers = {'Authorization': f'token {token}'}
    url = f'https://api.github.com/repos/{owner}/{repo}/contents/{file_path}'
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return data.get('sha')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command with GitHub token"""
    args = context.args
    if not args:
        await update.message.reply_text("Please provide your GitHub token: /start <your_token>")
        return ConversationHandler.END
    
    token = args[0]
    headers = {'Authorization': f'token {token}'}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('https://api.github.com/user', headers=headers) as resp:
                if resp.status != 200:
                    await update.message.reply_text("❌ Invalid token. Please try again.")
                    return ConversationHandler.END
                user_data = await resp.json()
    except Exception as e:
        await update.message.reply_text(f"🚨 Error verifying token: {str(e)}")
        return ConversationHandler.END

    context.user_data.update({
        'github_token': token,
        'github_username': user_data['login'],
        'repo_page': 1
    })

    keyboard = [
        [InlineKeyboardButton("Create Repository", callback_data='create_repo')],
        [InlineKeyboardButton("Update Repository", callback_data='update_repo')],
        [InlineKeyboardButton("Delete Repository", callback_data='delete_repo')]
    ]
    await update.message.reply_text(
        "✅ Successfully authenticated!\nChoose an action:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return AUTHENTICATED

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'create_repo':
        await query.edit_message_text("Please enter your repository name:")
        return GET_REPO_NAME
    elif query.data == 'update_repo':
        return await handle_update_repo(query, context)
    elif query.data.startswith('repo_page_'):
        page = int(query.data.split('_')[-1])
        context.user_data['repo_page'] = page
        return await show_repo_list(query, context)
    elif query.data.startswith('select_repo_'):
        repo_name = query.data[len('select_repo_'):]
        context.user_data['selected_repo'] = repo_name
        keyboard = [
            [InlineKeyboardButton("Create File", callback_data='repo_action_create')],
            [InlineKeyboardButton("Update File", callback_data='repo_action_update')],
            [InlineKeyboardButton("Delete File", callback_data='repo_action_delete')]
        ]
        await query.edit_message_text(
            f"Selected repository: {repo_name}\nChoose action:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REPO_ACTION
    elif query.data == 'repo_action_create':
        await query.edit_message_text("Send me the file to create:")
        return GET_FILE
    elif query.data == 'repo_action_update':
        return await handle_file_selection(query, context, mode='update')
    elif query.data == 'repo_action_delete':
        return await handle_file_selection(query, context, mode='delete')
    elif query.data.startswith('file_select_'):
        parts = query.data.split('_')
        mode = parts[2]
        file_path = '_'.join(parts[3:])
        context.user_data['selected_file'] = file_path
        if mode == 'update':
            await query.edit_message_text(f"Selected file: {file_path}\nSend me the new version:")
            return GET_UPDATE_FILE
        elif mode == 'delete':
            return await handle_file_deletion(query, context, file_path)
    elif query.data == 'delete_repo':
        return await handle_delete_repo(query, context)
    elif query.data.startswith('delete_repo_'):
        repo_name = query.data[len('delete_repo_'):]
        return await confirm_delete_repo(query, context, repo_name)
    elif query.data.startswith('delete_page_'):
        page = int(query.data.split('_')[-1])
        context.user_data['repo_page'] = page
        return await show_delete_repo_list(query, context)
    elif query.data == 'confirm_delete':
        return await execute_repo_deletion(query, context)
    elif query.data == 'cancel_delete':
        await query.edit_message_text("🗑️ Deletion cancelled")
        return ConversationHandler.END
    return AUTHENTICATED

async def handle_update_repo(query, context):
    """Handle repository selection for updates"""
    token = context.user_data['github_token']
    page = context.user_data.get('repo_page', 1)
    
    repos = await fetch_user_repos(token, page)
    if not repos:
        await query.edit_message_text("❌ Failed to fetch repositories")
        return ConversationHandler.END

    keyboard = []
    for repo in repos:
        keyboard.append([InlineKeyboardButton(
            repo['name'], callback_data=f'select_repo_{repo["name"]}'
        )])
    
    # Pagination controls
    pagination = []
    if page > 1:
        pagination.append(InlineKeyboardButton("⬅️ Previous", callback_data=f'repo_page_{page-1}'))
    pagination.append(InlineKeyboardButton(f"Page {page}", callback_data='#'))
    pagination.append(InlineKeyboardButton("Next ➡️", callback_data=f'repo_page_{page+1}'))
    keyboard.append(pagination)
    
    await query.edit_message_text(
        "Select a repository to manage:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_REPO

async def show_repo_list(query, context):
    """Show paginated repository list"""
    token = context.user_data['github_token']
    page = context.user_data['repo_page']
    
    repos = await fetch_user_repos(token, page)
    if not repos:
        await query.edit_message_text("❌ No more repositories found")
        return ConversationHandler.END

    keyboard = []
    for repo in repos:
        keyboard.append([InlineKeyboardButton(
            repo['name'], callback_data=f'select_repo_{repo["name"]}'
        )])
    
    pagination = []
    if page > 1:
        pagination.append(InlineKeyboardButton("⬅️ Previous", callback_data=f'repo_page_{page-1}'))
    pagination.append(InlineKeyboardButton(f"Page {page}", callback_data='#'))
    pagination.append(InlineKeyboardButton("Next ➡️", callback_data=f'repo_page_{page+1}'))
    keyboard.append(pagination)
    
    await query.edit_message_text(
        "Select a repository to manage:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_REPO

async def handle_file_selection(query, context, mode):
    """Handle file selection for update/delete operations"""
    token = context.user_data['github_token']
    owner = context.user_data['github_username']
    repo = context.user_data['selected_repo']
    
    url = f'https://api.github.com/repos/{owner}/{repo}/contents/'
    headers = {'Authorization': f'token {token}'}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    await query.edit_message_text("❌ Failed to fetch repository files")
                    return ConversationHandler.END
                files = await resp.json()
    except Exception as e:
        await query.edit_message_text(f"🚨 Error fetching files: {str(e)}")
        return ConversationHandler.END

    if not isinstance(files, list):
        await query.edit_message_text("❌ No files found in repository")
        return ConversationHandler.END

    keyboard = []
    for file in files:
        if file['type'] == 'file' and '/' not in file['path']:
            keyboard.append([InlineKeyboardButton(
                file['name'], callback_data=f'file_select_{mode}_{file["path"]}'
            )])
    
    if not keyboard:
        await query.edit_message_text("❌ No files found in repository root")
        return ConversationHandler.END
    
    await query.edit_message_text(
        f"Select file to {mode}:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_FILE_UPDATE if mode == 'update' else SELECT_FILE_DELETE

async def handle_file_deletion(query, context, file_path):
    """Handle file deletion process"""
    token = context.user_data['github_token']
    owner = context.user_data['github_username']
    repo = context.user_data['selected_repo']
    
    sha = await get_file_sha(token, owner, repo, file_path)
    if not sha:
        await query.edit_message_text("❌ File not found in repository")
        return ConversationHandler.END

    url = f'https://api.github.com/repos/{owner}/{repo}/contents/{file_path}'
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    data = {
        'message': f'Delete {file_path} via Telegram Bot',
        'sha': sha
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers, json=data) as resp:
                if resp.status not in (200, 204):
                    await query.edit_message_text("❌ Failed to delete file")
                    return ConversationHandler.END
    except Exception as e:
        await query.edit_message_text(f"🚨 Error deleting file: {str(e)}")
        return ConversationHandler.END

    await query.edit_message_text(f"✅ Successfully deleted file: {file_path}")
    return ConversationHandler.END

async def get_repo_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle repository name input and create repo"""
    repo_name = update.message.text.strip()
    token = context.user_data['github_token']
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    data = {
        'name': repo_name,
        'auto_init': False,
        'private': False
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://api.github.com/user/repos',
                headers=headers,
                json=data
            ) as resp:
                if resp.status not in (200, 201):
                    await update.message.reply_text("❌ Failed to create repository. Please try again.")
                    return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"🚨 Error creating repository: {str(e)}")
        return ConversationHandler.END

    context.user_data['repo_name'] = repo_name
    await update.message.reply_text("📁 Repository created! Now send me a file to upload:")
    return GET_FILE

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file upload and commit to GitHub"""
    if not update.message.document:
        await update.message.reply_text("Please send a file.")
        return GET_FILE

    # Determine file path based on mode
    if context.user_data.get('update_mode'):
        file_path = context.user_data['selected_file']
    else:
        file_path = update.message.document.file_name

    # Download file from Telegram
    file = await update.message.document.get_file()
    file_content = await file.download_as_bytearray()

    # Get repository information
    token = context.user_data['github_token']
    owner = context.user_data['github_username']
    repo = context.user_data.get('selected_repo') or context.user_data.get('repo_name')
    
    # GitHub API request
    url = f'https://api.github.com/repos/{owner}/{repo}/contents/{file_path}'
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    # Check if file exists for update
    sha = None
    if context.user_data.get('update_mode'):
        sha = await get_file_sha(token, owner, repo, file_path)

    data = {
        'message': 'File update from Telegram Bot' if sha else 'File creation from Telegram Bot',
        'content': base64.b64encode(file_content).decode('utf-8')
    }
    if sha:
        data['sha'] = sha

    try:
        async with aiohttp.ClientSession() as session:
            if sha:
                async with session.put(url, headers=headers, json=data) as resp:
                    if resp.status not in (200, 201):
                        await update.message.reply_text("❌ Failed to update file. Please try again.")
                        return ConversationHandler.END
            else:
                async with session.put(url, headers=headers, json=data) as resp:
                    if resp.status not in (200, 201):
                        await update.message.reply_text("❌ Failed to upload file. Please try again.")
                        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"🚨 Error uploading file: {str(e)}")
        return ConversationHandler.END

    # Clean up update_mode flag
    context.user_data.pop('update_mode', None)

    # Send final repository link
    repo_url = f'https://github.com/{owner}/{repo}.git'
    action = "updated" if sha else "created"
    await update.message.reply_text(f"✅ File {action} successfully!\nRepository URL: {repo_url}")
    return ConversationHandler.END

async def get_update_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle updated file content"""
    context.user_data['update_mode'] = True
    return await handle_file_upload(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation"""
    await update.message.reply_text('Operation cancelled.')
    return ConversationHandler.END

async def handle_delete_repo(query, context):
    """Handle repository deletion flow"""
    context.user_data['repo_page'] = 1
    return await show_delete_repo_list(query, context)

async def show_delete_repo_list(query, context):
    """Show paginated repos for deletion"""
    token = context.user_data['github_token']
    page = context.user_data['repo_page']
    
    repos = await fetch_user_repos(token, page)
    if not repos:
        await query.edit_message_text("❌ No repositories found")
        return ConversationHandler.END

    keyboard = []
    for repo in repos:
        keyboard.append([InlineKeyboardButton(
            repo['name'], callback_data=f'delete_repo_{repo["name"]}'
        )])
    
    # Pagination controls
    pagination = []
    if page > 1:
        pagination.append(InlineKeyboardButton("⬅️ Previous", callback_data=f'delete_page_{page-1}'))
    pagination.append(InlineKeyboardButton(f"Page {page}", callback_data='#'))
    pagination.append(InlineKeyboardButton("Next ➡️", callback_data=f'delete_page_{page+1}'))
    keyboard.append(pagination)
    
    await query.edit_message_text(
        "Select a repository to DELETE:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return DELETE_REPO

async def confirm_delete_repo(query, context, repo_name):
    """Ask for deletion confirmation"""
    context.user_data['repo_to_delete'] = repo_name
    keyboard = [
        [InlineKeyboardButton("Yes, Delete", callback_data='confirm_delete')],
        [InlineKeyboardButton("Cancel", callback_data='cancel_delete')]
    ]
    await query.edit_message_text(
        f"⚠️ Are you SURE you want to delete {repo_name}? This action cannot be undone!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CONFIRM_DELETE_REPO

async def execute_repo_deletion(query, context):
    """Perform actual repository deletion"""
    token = context.user_data['github_token']
    owner = context.user_data['github_username']
    repo_name = context.user_data['repo_to_delete']
    
    url = f'https://api.github.com/repos/{owner}/{repo_name}'
    headers = {'Authorization': f'token {token}'}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as resp:
                if resp.status != 204:
                    await query.edit_message_text("❌ Failed to delete repository")
                    return ConversationHandler.END
    except Exception as e:
        await query.edit_message_text(f"🚨 Error deleting repository: {str(e)}")
        return ConversationHandler.END

    await query.edit_message_text(f"✅ Successfully deleted repository: {repo_name}")
    return ConversationHandler.END

def main():
    """Start the bot"""
    bot_token = "7788535284:AAEUMBlNsVqP31MyK8eVPjbwrOEfUmfudzk"
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

    app = Application.builder().token(bot_token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            AUTHENTICATED: [CallbackQueryHandler(handle_button_click)],
            GET_REPO_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_repo_name)],
            GET_FILE: [MessageHandler(filters.Document.ALL, handle_file_upload)],
            SELECT_REPO: [CallbackQueryHandler(handle_button_click)],
            REPO_ACTION: [CallbackQueryHandler(handle_button_click)],
            SELECT_FILE_UPDATE: [CallbackQueryHandler(handle_button_click)],
            SELECT_FILE_DELETE: [CallbackQueryHandler(handle_button_click)],
            GET_UPDATE_FILE: [MessageHandler(filters.Document.ALL, get_update_file)],
            DELETE_REPO: [CallbackQueryHandler(handle_button_click)],
            CONFIRM_DELETE_REPO: [CallbackQueryHandler(handle_button_click)]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )

    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == '__main__':
    main()
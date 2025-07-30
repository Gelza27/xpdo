import asyncio
import aiohttp
import time
import tempfile
import os
import random
from typing import List
from telegram import Update, Document
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import logging

# Configure minimal logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = "7226730325:AAFkGpAhGTsnWmoMIUnQSPzzIptzZrv3Oi8"
GROUP_ID = -1002804460072

class SimpleProxyTester:
    def __init__(self):
        self.test_urls = ["http://httpbin.org/ip", "http://api.ipify.org"]
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Connection': 'close'
        }

    async def test_single_proxy(self, proxy: str) -> bool:
        try:
            parts = proxy.strip().split(':')
            if len(parts) < 2:
                return False

            ip, port = parts[0], parts[1]
            ip_parts = ip.split('.')
            if len(ip_parts) != 4 or not all(0 <= int(p) <= 255 for p in ip_parts):
                return False
            if not 1 <= int(port) <= 65535:
                return False

            proxy_url = f"http://{ip}:{port}"
            timeout_obj = aiohttp.ClientTimeout(total=10, connect=5)
            connector = aiohttp.TCPConnector(limit=1, force_close=True)

            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout_obj,
                headers=self.headers
            ) as session:
                async with session.get(self.test_urls[0], proxy=proxy_url, ssl=False) as response:
                    return response.status == 200

        except Exception:
            return False

class SimpleProxyBot:
    def __init__(self, token: str, group_id: int):
        self.token = token
        self.group_id = group_id
        self.tester = SimpleProxyTester()
        self.bot_instance = None

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        welcome_msg = """🔍 **Simple Proxy Checker Bot**"""
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        document: Document = update.message.document

        if not document.file_name.lower().endswith('.txt'):
            await update.message.reply_text("❌ Please send a .txt file")
            return

        status_msg = await update.message.reply_text("📥 **Processing file...**", parse_mode='Markdown')

        try:
            file = await context.bot.get_file(document.file_id)

            with tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False) as temp_file:
                await file.download_to_drive(temp_file.name)
                temp_file_path = temp_file.name

            with open(temp_file_path, 'r', encoding='utf-8') as f:
                raw_proxies = [line.strip() for line in f.readlines() if line.strip()]

            valid_proxies = [proxy for proxy in raw_proxies if ':' in proxy and len(proxy.split(':')) >= 2]

            if not valid_proxies:
                await status_msg.edit_text("❌ **No valid proxy formats found**", parse_mode='Markdown')
                return

            await status_msg.edit_text(
                f"📋 **File loaded!**\n"
                f"Total proxies: {len(valid_proxies)}\n"
                f"🔄 **Starting tests with 10 workers...**",
                parse_mode='Markdown'
            )

            self.bot_instance = context.bot
            await self.test_proxies_concurrent(valid_proxies, update, status_msg)

        except Exception as e:
            logger.error(f"Error: {e}")
            await status_msg.edit_text(f"❌ **Error:** {str(e)}", parse_mode='Markdown')
        finally:
            if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    async def send_to_group(self, proxy: str):
        try:
            if self.bot_instance:
                await self.bot_instance.send_message(
                    chat_id=self.group_id,
                    text=f"`{proxy}`",
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Failed to send to group: {e}")

    async def test_proxies_concurrent(self, proxies: List[str], update: Update, status_msg):
        total_proxies = len(proxies)
        tested = 0
        working = 0
        failed = 0
        working_proxies: List[str] = []
        semaphore = asyncio.Semaphore(100)  # Limit concurrency to 10

        async def test_and_track(proxy: str):
            nonlocal tested, working, failed

            async with semaphore:
                success = await self.tester.test_single_proxy(proxy)
                tested += 1

                if success:
                    working += 1
                    working_proxies.append(proxy)
                    await self.send_to_group(proxy)
                else:
                    failed += 1

                if tested % 10 == 0 or success:
                    try:
                        percent = (tested / total_proxies) * 100
                        success_rate = (working / tested) * 100 if tested > 0 else 0
                        progress = (
                            f"🔄 **Testing Progress**\n\n"
                            f"📊 **Stats:**\n"
                            f"• Tested: {tested}/{total_proxies}\n"
                            f"• Working: {working} ✅\n"
                            f"• Failed: {failed} ❌\n"
                            f"• Success Rate: {success_rate:.1f}%\n\n"
                            f"⏳ Current: {tested}/{total_proxies} ({percent:.1f}%)"
                        )
                        await status_msg.edit_text(progress, parse_mode='Markdown')
                    except Exception as e:
                        logger.error(f"Failed to update progress: {e}")

        await asyncio.gather(*(test_and_track(proxy) for proxy in proxies))
        await self.send_final_results(update, working_proxies, tested, working, failed)

    async def send_final_results(self, update: Update, working_proxies: List[str], tested: int, working: int, failed: int):
        final_msg = f"✅ **Testing Complete!**\n\n" \
                    f"📊 **Final Results:**\n" \
                    f"• Total Tested: {tested}\n" \
                    f"• Working: {working} ✅\n" \
                    f"• Failed: {failed} ❌\n" \
                    f"• Success Rate: {(working/tested*100):.1f}%\n\n" \
                    f"📤 All working proxies sent to group!\n" \
                    f"📁 Result file below ⬇️"

        await update.message.reply_text(final_msg, parse_mode='Markdown')

        if working_proxies:
            timestamp = int(time.time())
            content = "\n".join(working_proxies)

            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
                f.write(content)
                result_file = f.name

            try:
                with open(result_file, 'rb') as f:
                    await update.message.reply_document(
                        document=f,
                        filename=f"working_proxies_{timestamp}.txt",
                        caption=f"📁 **Working Proxies** ({len(working_proxies)} proxies)\n⏱️ Tested at {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
            finally:
                if os.path.exists(result_file):
                    os.unlink(result_file)
        else:
            await update.message.reply_text("❌ **No working proxies found**")

def main():

    bot = SimpleProxyBot(BOT_TOKEN, GROUP_ID)
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_document))

    print("Done...")

    try:
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        print(f"❌ Bot error: {e}")

if __name__ == "__main__":
    main()

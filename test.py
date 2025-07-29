import telebot
import threading
import time

# Replace 'YOUR_BOT_TOKEN' with your real token
TOKEN = '8172739451:AAH7KFOxKU3vZyJFMAgrpA7WMe-dLNaqbiY'
bot = telebot.TeleBot(TOKEN)
chat_state = {}

def ping_user(chat_id):
    while chat_state.get(chat_id):
        bot.send_message(chat_id, "Ping!")
        time.sleep(60)  # Wait one minute

@bot.message_handler(commands=['start'])
def start_handler(message):
    bot.reply_to(message, "hii I am alive")

@bot.message_handler(commands=['ping'])
def ping_handler(message):
    chat_id = message.chat.id
    if not chat_state.get(chat_id):
        chat_state[chat_id] = True
        bot.reply_to(message, "I'll ping you every minute!")
        threading.Thread(target=ping_user, args=(chat_id,), daemon=True).start()
    else:
        bot.reply_to(message, "Already pinging you every minute!")

@bot.message_handler(commands=['stop'])
def stop_handler(message):
    chat_id = message.chat.id
    chat_state[chat_id] = False
    bot.reply_to(message, "Ping stopped.")

bot.polling()

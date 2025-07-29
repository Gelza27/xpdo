import telebot

# Replace 'YOUR_BOT_TOKEN' with your actual bot token from BotFather
bot = telebot.TeleBot('8172739451:AAH7KFOxKU3vZyJFMAgrpA7WMe-dLNaqbiY')

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, 'hii I am alive')

bot.polling()

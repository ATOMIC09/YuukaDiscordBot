from chatterbot import ChatBot
from chatterbot.trainers import ChatterBotCorpusTrainer
import os

def train_from_chat():
    bot = ChatBot('Yuuka')
    trainer = ChatterBotCorpusTrainer(bot)
    trainer.train('asset/chat')

def train_english():
    bot = ChatBot('Yuuka')
    trainer = ChatterBotCorpusTrainer(bot)
    trainer.train('chatterbot.corpus.english')

def train_thai():
    bot = ChatBot('Yuuka')
    trainer = ChatterBotCorpusTrainer(bot)
    trainer.train('chatterbot.corpus.thai')

def get_response(text):
    bot = ChatBot('Yuuka')
    response = bot.get_response(text)
    return response

def delete_chat():
    dir = 'asset/chat'
    for f in os.listdir(dir):
        os.remove(os.path.join(dir, f))
        
def delete_db():
    os.remove('db.sqlite3')

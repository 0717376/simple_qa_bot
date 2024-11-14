import csv
import json
import aiohttp
import asyncio
from typing import Dict
import sys
import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class Config:
    BASE_URL = os.getenv('BASE_URL')
    API_KEY = os.getenv('API_KEY')
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

def read_csv_context(filename: str = 'запросы-ответы.csv') -> str:
    """Читает CSV файл и форматирует его в текстовый контекст."""
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            content = file.read()
            file.seek(0)
            
            dialect = csv.Sniffer().sniff(content)
            reader = csv.DictReader(file, dialect=dialect)
            
            question_field = None
            answer_field = None
            
            for field in reader.fieldnames:
                if 'вопрос' in field.lower():
                    question_field = field
                elif 'ответ' in field.lower():
                    answer_field = field
            
            if not question_field or not answer_field:
                raise ValueError(f"Не найдены нужные колонки. Доступные колонки: {reader.fieldnames}")
            
            file.seek(0)
            reader = csv.DictReader(file, dialect=dialect)
            
            qa_pairs = [f"Вопрос: {row[question_field]}\nОтвет: {row[answer_field]}" 
                       for row in reader if row[question_field] and row[answer_field]]
            
            return '\n\n'.join(qa_pairs)
            
    except Exception as e:
        logger.error(f"Ошибка при чтении файла: {str(e)}")
        raise

def create_api_request(context: str, user_question: str) -> Dict:
    """Создает структуру запроса к API."""
    return {
        "model": "cotype_pro_16k_1.1",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты - ассистент компании Voxys. Используй только информацию "
                    "из предоставленного контекста для ответов на вопросы. "
                    "Если информации нет в контексте, отвечай 'Нет информации'.\n\n"
                    f"Контекст вопросов и ответов:\n\n{context}"
                )
            },
            {
                "role": "user",
                "content": user_question
            }
        ]
    }

async def send_api_request(request_data: Dict) -> str:
    """Отправляет запрос к API и возвращает ответ."""
    try:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {Config.API_KEY}'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{Config.BASE_URL}/v1/chat/completions",
                headers=headers,
                json=request_data,
                timeout=30
            ) as response:
                response.raise_for_status()
                result = await response.json()
                
                return result.get('choices', [{}])[0].get('message', {}).get('content', 
                                                                    'Ошибка: Не удалось получить ответ')
        
    except Exception as e:
        logger.error(f"Ошибка при отправке запроса к API: {str(e)}")
        return f"Извините, произошла ошибка при обработке запроса. Попробуйте позже."

async def keep_typing(chat):
    """Поддерживает индикацию печатания активной"""
    while True:
        await chat.send_action(action="typing")
        await asyncio.sleep(5)  # Telegram требует обновлять статус каждые 5 секунд

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    await update.message.reply_text(
        "Привет! Я помощник компании Voxys. Задайте мне вопрос, и я постараюсь на него ответить."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help."""
    help_text = (
        "Я могу ответить на ваши вопросы о компании Voxys.\n"
        "Просто напишите свой вопрос, и я постараюсь помочь.\n"
        "Доступные команды:\n"
        "/start - Начать диалог\n"
        "/help - Показать это сообщение"
    )
    await update.message.reply_text(help_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений."""
    try:
        # Получаем контекст из CSV при первом запросе
        if not hasattr(context.bot_data, 'qa_context'):
            context.bot_data['qa_context'] = read_csv_context()
        
        user_question = update.message.text
        
        # Создаём задачу для поддержания индикации печатания
        typing_task = asyncio.create_task(keep_typing(update.message.chat))
        
        try:
            # Создаем и отправляем запрос
            request_data = create_api_request(context.bot_data['qa_context'], user_question)
            response = await send_api_request(request_data)
            
            await update.message.reply_text(response)
        finally:
            # Останавливаем индикацию печатания
            typing_task.cancel()
            
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {str(e)}")
        await update.message.reply_text(
            "Извините, произошла ошибка при обработке вашего запроса. "
            "Пожалуйста, попробуйте позже."
        )

def main() -> None:
    """Запуск бота."""
    try:
        # Создаем приложение
        application = Application.builder().token(Config.TELEGRAM_TOKEN).build()

        # Добавляем обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # Запускаем бота
        print("Бот запущен. Нажмите Ctrl+C для остановки.")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()
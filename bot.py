import asyncio
import logging
import os
import json
from typing import Dict, Any
from dataclasses import dataclass, asdict
from dotenv import load_dotenv
load_dotenv()

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardRemove, Update
from aiogram import BaseMiddleware

BOT_TOKEN = os.getenv("BOT_TOKEN")  
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")  

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler,
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        if event.message:
            user = event.message.from_user
            command = event.message.text or ""
            logger.info(f"User {user.id} (@{user.username}): {command}")
        
        return await handler(event, data)
    
@dataclass
class UserProfile:
    weight: float=70.0
    height: int=170
    age: int=25
    gender: str= "male"
    activity_minutes: int = 30
    city: str = "Moscow"
    water_goal: float=0.0
    calorie_goal: float=0.0
    logged_water: float=0.0
    logged_calories: float=0.0
    burned_calories: float=0.0

users: Dict[int, UserProfile] = {}

class ProfileStates(StatesGroup):
    weight= State()
    height= State()
    age= State()
    gender =State()
    activity =State()
    city =State()

class FoodStates(StatesGroup):
    grams = State()

METS = {
    "бег": 10.0,
    "велосипед": 8.0,
    "плавание": 6.0,
    "прогулка": 2.0,
    "default": 1.0
}
dp = Dispatcher(storage=MemoryStorage())
profile_router = Router()
food_router = Router()
dp.include_router(profile_router)
dp.include_router(food_router)

dp.update.middleware(LoggingMiddleware())

async def get_weather_temp(city: str) -> float:
    """Получить температуру по городу """
    if not WEATHER_API_KEY:
        return 20.0
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["main"]["temp"]
    return 20.0

def calculate_bmr(profile: UserProfile) -> float:
    """Формула для расчета калорийности """
    if profile.gender == "male":
        return 10* profile.weight+6.25 *profile.height - 5*profile.age +5
    return 10*profile.weight+ 6.25* profile.height- 5*profile.age- 161

def calculate_calorie_goal(profile: UserProfile) -> float:
    """Формула расчета общих калорий исходя из активности"""
    bmr = calculate_bmr(profile)
    activity_factor = 1.2 + (profile.activity_minutes/1440)*0.5  
    return bmr*activity_factor

def calculate_water_goal(profile: UserProfile, temp: float) -> float:
    """Формула для расчета воды"""
    base = profile.weight* 30
    activity_bonus = (profile.activity_minutes //30)*500
    weather_bonus = 750 if temp>25 else 0
    return base + activity_bonus + weather_bonus

def get_calories_burned(activity_type: str, minutes: int, weight: float) -> float:
    """Количество калорий исходя из тренировки"""
    met = METS.get(activity_type.lower(), METS["default"])
    return (met *3.5*weight / 200)* minutes

import urllib.parse

async def get_food_calories(product_name: str) -> float:
    encoded = urllib.parse.quote(product_name)
    url = f"https://world.openfoodfacts.org/cgi/search.pl?action=process&search_terms={encoded}&json=1&page_size=20"
    
    try:
        timeout = aiohttp.ClientTimeout(total=10)  # Увеличено
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                print(f"Status: {resp.status} for '{product_name}'")  # Дебаг
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Count: {data.get('count',0)}")  # Дебаг
                    products = data.get('products', [])
                    if products:
                        calories = products[0].get('nutriments', {}).get('energy-kcal_100g', 0)
                        return float(calories) if calories else 0.0
    except Exception as e:
        logging.error(f"Error: {e}")
    return 0.0

@profile_router.message(Command("set_profile"))
async def set_profile_start(message: Message, state: FSMContext):
    await state.set_state(ProfileStates.weight)
    await message.answer("Введите ваш вес (кг):")

@profile_router.message(ProfileStates.weight)
async def process_weight(message: Message, state: FSMContext):
    try:
        weight = float(message.text)
        await state.update_data(weight=weight)
        await state.set_state(ProfileStates.height)
        await message.answer("Введите рост (см):")
    except ValueError:
        await message.answer("Неверный формат. Введите число:")

@profile_router.message(ProfileStates.height)
async def process_height(message: Message, state: FSMContext):
    try:
        height = int(message.text)
        await state.update_data(height=height)
        await state.set_state(ProfileStates.age)
        await message.answer("Введите возраст:")
    except ValueError:
        await message.answer("Неверный формат. Введите число:")

@profile_router.message(ProfileStates.age)
async def process_age(message: Message, state: FSMContext):
    try:
        age = int(message.text)
        await state.update_data(age=age)
        await state.set_state(ProfileStates.gender)
        await message.answer("Пол (male/female):")
    except ValueError:
        await message.answer("Неверный формат. Введите male или female:")

@profile_router.message(ProfileStates.gender)
async def process_gender(message: Message, state: FSMContext):
    gender = message.text.lower()
    if gender in ["male", "female"]:
        await state.update_data(gender=gender)
        await state.set_state(ProfileStates.activity)
        await message.answer("Минут активности в день:")
    else:
        await message.answer("Введите male или female:")

@profile_router.message(ProfileStates.activity)
async def process_activity(message: Message, state: FSMContext):
    try:
        activity = int(message.text)
        await state.update_data(activity_minutes=activity)
        await state.set_state(ProfileStates.city)
        await message.answer("Город:")
    except ValueError:
        await message.answer("Неверный формат. Введите город:")

@profile_router.message(ProfileStates.city)
async def process_city(message: Message, state: FSMContext):
    data = await state.get_data()
    profile = UserProfile(**data)
    profile.city = message.text.capitalize()
    
    temp = await get_weather_temp(profile.city)
    profile.water_goal=calculate_water_goal(profile, temp)
    profile.calorie_goal= calculate_calorie_goal(profile)
    
    users[message.from_user.id]= profile
    
    await state.clear()
    await message.answer(
        f"Профиль сохранен!\n"
        f"Норма воды: {profile.water_goal:.0f} мл\n"
        f"Норма калорий: {profile.calorie_goal:.0f} ккал\n"
        f"Температура в {profile.city}: {temp:.1f} C",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.message(Command("log_water"))
async def log_water(message: Message):
    try:
        amount_text= " ".join(message.text.split()[1:]).replace("мл", "").replace(" ", "").strip()
        amount=float(amount_text)
        
        user_id= message.from_user.id
        if user_id in users:
            users[user_id].logged_water += amount
            remain= max(0, users[user_id].water_goal - users[user_id].logged_water)
            await message.answer(f"Записано {amount} мл. Осталось: {remain:.0f} мл")
        else:
            await message.answer("Сначала /set_profile")
    except:
        await message.answer("Формат: /log_water 400")

@food_router.message(Command("log_food"))
async def log_food_start(message: Message, state: FSMContext):
    food =message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
    if not food:
        await message.answer("Использование: /log_food <продукт>")
        return
    await state.update_data(food=food)
    await state.set_state(FoodStates.grams)
    await message.answer(f"{food} — сколько грамм съели?")

@food_router.message(FoodStates.grams)
async def process_food_grams(message: Message, state: FSMContext):
    try:
        grams = float(message.text.strip())
        
        if grams <= 0 or grams > 5000:
            await message.answer("Введите разумное количество грамм (1-5000):")
            return
        
        data=await state.get_data()
        food_name = data["food"]
        
        kcal_per_100g =await get_food_calories(food_name)
        
        if kcal_per_100g <= 0:
            await message.answer(f"Не удалось найти данные о {food_name}. Используйте /log_food снова.")
            await state.clear()
            return
        
        calories = (kcal_per_100g*grams)/100
        
        user_id= message.from_user.id
        if user_id in users:
            users[user_id].logged_calories += calories
            await message.answer(
                f"Записано: {calories:.1f} ккал от {grams}г {food_name}\n"
                f"(Калорийность: {kcal_per_100g:.1f} ккал/100г)"
            )
        else:
            await message.answer("Сначала настройте профиль: /set_profile")
        
        await state.clear()
        
    except ValueError:
        await message.answer("Неверный формат. Введите число грамм (например: 100):")
    except Exception as e:
        logging.error(f"Ошибка в процессе: {e}")
        await message.answer("Произошла ошибка. Попробуйте еще раз.")
        await state.clear()

@dp.message(Command("log_workout"))
async def log_workout(message: Message):
    parts =message.text.split()
    if len(parts)<3:
        await message.answer("Использование: /log_workout <тип> <мин> Например: /log_workout бег 30")
        return
    activity_type = parts[1]
    minutes= float(parts[2])
    user_id = message.from_user.id
    if user_id in users:
        profile= users[user_id]
        burned= get_calories_burned(activity_type, minutes, profile.weight)
        profile.burned_calories += burned
        water_extra=(minutes//30)*200
        profile.water_goal += water_extra 
        await message.answer(
            f" {activity_type.capitalize()} {minutes} мин —{burned:.0f} ккал сожжено.\n"
            f"Дополнительное количество воды: {water_extra} мл"
        )
    else:
        await message.answer("Сначала /set_profile")

@dp.message(Command("check_progress"))
async def check_progress(message: Message):
    user_id= message.from_user.id
    if user_id not in users:
        await message.answer("Сначала настройте профиль: /set_profile")
        return
    profile =users[user_id]
    temp= await get_weather_temp(profile.city)
    profile.water_goal=calculate_water_goal(profile, temp)  
    
    water_remain= max(0, profile.water_goal - profile.logged_water)
    cal_remain= max(0, profile.calorie_goal - profile.logged_calories + profile.burned_calories)
    
    text = f""" Прогресс:
    
Вода:
- Выпито: {profile.logged_water:.0f} мл из {profile.water_goal:.0f} мл
- Осталось: {water_remain:.0f} мл

Калории:
- Потреблено: {profile.logged_calories:.0f} ккал из {profile.calorie_goal:.0f}
- Сожжено: {profile.burned_calories:.0f} ккал
- Осталось: {cal_remain:.0f} ккал"""
    await message.answer(text)

@dp.message(Command("delete_day"))
async def delete_day(message: Message):
    if message.from_user.id in users:
        users[message.from_user.id].logged_water = 0
        users[message.from_user.id].logged_calories = 0
        users[message.from_user.id].burned_calories = 0
        await message.answer("Дневные данные сброшены!")
        
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет! Я бот для трекинга воды, калорий и активности.\n"
        "Команды:\n"
        "/set_profile - настройка\n"
        "/log_water <мл> - вода\n"
        "/log_food <еда> - еда\n"
        "/log_workout <тип> <мин> - тренировка\n"
        "/delete_day - сброс дня"
        "/check_progress - прогресс"
    )

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не найден!")
        return
    
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
  
    logger.info("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Бот выдает ошибку: {e}")

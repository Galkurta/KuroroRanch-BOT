import asyncio
import json
import time
import logging
from datetime import datetime
from urllib.parse import unquote
from colorama import init
from hydrogram import Client
from hydrogram.raw.functions.messages import RequestWebView
from hydrogram.errors import SessionPasswordNeeded
from pathlib import Path
import glob
import requests
from concurrent.futures import ThreadPoolExecutor
from json import JSONDecodeError
import colorlog

init(autoreset=True)

log_colors_config = {
    'DEBUG': 'cyan',
    'INFO': 'green',
    'WARNING': 'yellow',
    'ERROR': 'red',
    'CRITICAL': 'red,bg_white',
}

handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s - %(levelname)s - %(message)s',
    log_colors=log_colors_config
))

logger = colorlog.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

DEVICE_MODEL = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0")
SYSTEM_VERSION = "Win32"
APP_VERSION = "2.1.0 K"
SESSION_FOLDER = Path("sessions")

def read_auth_tokens_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return [line.strip() for line in file.readlines()]

def read_proxies_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return [line.strip() for line in file.readlines()]

def read_config_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)

def create_headers(auth_token):
    return {
        "Accept": "*/*",
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Origin": "https://ranch.kuroro.com",
        "Priority": "u=1, i",
        "Referer": "https://ranch.kuroro.com/",
        "Sec-Ch-Ua": "\"Chromium\";v=\"124\", \"Google Chrome\";v=\"124\", \"Not-A.Brand\";v=\"99\"",
        "Sec-Ch-Ua-Mobile": "?1",
        "Sec-Ch-Ua-Platform": "\"Android\"",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": ("Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")
    }

def get_proxy_dict(proxy):
    proxy_parts = proxy.split('@')
    if len(proxy_parts) == 2:
        auth, ip_port = proxy_parts
        if ':' in auth:
            username, password = auth.split(':', 1)
            return {
                "http": f"http://{username}:{password}@{ip_port}",
                "https": f"https://{username}:{password}@{ip_port}"
            }
    else:
        ip_port = proxy_parts[0]
        return {
            "http": f"http://{ip_port}",
            "https": f"https://{ip_port}"
        }
    return None

def get_daily_streak_state(headers, proxy_dict=None):
    url = "https://ranch-api.kuroro.com/api/DailyStreak/GetState"
    return requests.get(url, headers=headers, proxies=proxy_dict)

def claim_daily_bonus(headers, proxy_dict=None):
    url = "https://ranch-api.kuroro.com/api/DailyStreak/ClaimDailyBonus"
    return requests.post(url, headers=headers, proxies=proxy_dict)

def perform_farming_and_feeding(headers, mine_amount, feed_amount, proxy_dict=None):
    url = "https://ranch-api.kuroro.com/api/Clicks/MiningAndFeeding"
    data = {"mineAmount": mine_amount, "feedAmount": feed_amount}
    return requests.post(url, headers=headers, json=data, proxies=proxy_dict)

def get_purchasable_upgrades(headers, proxy_dict=None):
    url = "https://ranch-api.kuroro.com/api/Upgrades/GetPurchasableUpgrades"
    return requests.get(url, headers=headers, proxies=proxy_dict)

def buy_upgrade(headers, upgrade_id, proxy_dict=None):
    url = "https://ranch-api.kuroro.com/api/Upgrades/BuyUpgrade"
    data = {"upgradeId": upgrade_id}
    return requests.post(url, headers=headers, json=data, proxies=proxy_dict)

def process_account(auth_token, coin_limit, account_number, use_proxy, proxies):
    logger.info(f"Login to account {account_number}")
    headers = create_headers(auth_token)
    
    proxy_dict = None
    if use_proxy:
        proxy_index = account_number % len(proxies)
        proxy = proxies[proxy_index]
        proxy_dict = get_proxy_dict(proxy)
        logger.info(f"Using proxy: {proxy}")

    state_response = get_daily_streak_state(headers, proxy_dict)
    if state_response.status_code == 200:
        state_data = state_response.json()
        if not state_data['isTodayClaimed']:
            logger.info("Logged in successfully! You have not received the reward today.")
            claim_response = claim_daily_bonus(headers, proxy_dict)
            if claim_response.status_code == 200:
                claim_data = claim_response.json()
                logger.info(f"{claim_data['message']}")
            else:
                logger.warning("Reward already claimed today")
        else:
            logger.info("Logged in successfully! You have received the reward today.")
        
        mine_amount = 100
        feed_amount = 100
        farm_response = perform_farming_and_feeding(headers, mine_amount, feed_amount, proxy_dict)
        if farm_response.status_code == 200:
            try:
                farm_data = farm_response.json()
                logger.info(f"Farm and feed successful: {farm_data}")
            except JSONDecodeError:
                logger.warning("Farm and feed successful but did not receive JSON feedback.")
                logger.warning(f"Response text: {farm_response.text}")
        elif farm_response.status_code == 500:
            logger.warning("The energy is not enough to farm and feed the pet.")
            upgrades_response = get_purchasable_upgrades(headers, proxy_dict)
            if upgrades_response.status_code == 200:
                upgrades_data = upgrades_response.json()
                upgrades_purchased = False
                logger.info("Purchasable upgrades:")
                for upgrade in upgrades_data:
                    if upgrade["canBePurchased"] and upgrade["cost"] < coin_limit:
                        logger.info(f"Buying upgrade: {upgrade['name']} for {upgrade['cost']} coins")
                        buy_response = buy_upgrade(headers, upgrade["upgradeId"], proxy_dict)
                        if buy_response.status_code == 200:
                            logger.info(f"Successfully bought {upgrade['name']} for {upgrade['cost']} coins, earning {upgrade['earnIncrement']} per hour")
                            upgrades_purchased = True
                        else:
                            logger.warning(f"Failed to buy upgrade {upgrade['name']}")
                if not upgrades_purchased:
                    logger.info(f"No upgrades available for less than {coin_limit} coins.")
            else:
                logger.error("Cannot get list of purchasable upgrades")
        else:
            logger.error("Farm and feed failed")
            logger.error(f"Response content: {farm_response.text}")
    else:
        logger.error("Login failed")

async def telegram(phone: str, return_data: bool, config, proxies, use_proxy):
    if not SESSION_FOLDER.exists():
        SESSION_FOLDER.mkdir(parents=True)

    proxy_dict = None
    if use_proxy and proxies:
        proxy_index = hash(phone) % len(proxies)
        proxy = proxies[proxy_index]
        proxy_dict = get_proxy_dict(proxy)
        logger.info(f"Using proxy: {proxy}")

    client = Client(
        phone,
        api_id=config['api_id'],
        api_hash=config['api_hash'],
        device_model=DEVICE_MODEL,
        workdir=str(SESSION_FOLDER),
        system_version=SYSTEM_VERSION,
        app_version=APP_VERSION,
        proxy=proxy_dict,
    )
    if not await client.connect():
        try:
            result = await client.send_code(phone)
            code = input("Input login code: ")
            await client.sign_in(
                phone_code=code,
                phone_number=phone,
                phone_code_hash=result.phone_code_hash,
            )
        except SessionPasswordNeeded:
            pw2fa = input("Input password 2FA: ")
            await client.check_password(pw2fa)

    me = await client.get_me()
    logger.info(f"Name: {me.first_name} {me.last_name}\nUsername: {me.username}")

    if return_data:
        try:
            peer = await client.resolve_peer('KuroroRanchBot')
            webview = await client.invoke(RequestWebView(
                peer=peer,
                bot=peer,
                from_bot_menu=False,
                platform='Android',
                url='https://ranch.kuroro.com/'
            ))
            query = unquote(webview.url.split("&tgWebAppVersion=")[0].split("#tgWebAppData=")[1])
            with open("data.txt", "a") as file:
                file.write(f"{query}\n")
            logger.info("Saved data to data.txt")
        except Exception as e:
            logger.error(f"Error retrieving query data: {str(e)}")

    await client.disconnect()
    return True

async def main_telegram(config, proxies):
    menus = """
    1. Create session
    2. Get query from session
    """
    print(menus)
    opt = input("Input number: ")
    use_proxy = config.get("use_proxy", False)
    if opt == "1":
        phone = input("Input phone number (+): ")
        await telegram(phone=phone, return_data=False, config=config, proxies=proxies, use_proxy=use_proxy)
    elif opt == "2":
        sessions = glob.glob(str(SESSION_FOLDER / "*.session"))
        for session in sessions:
            phone = Path(session).stem
            await telegram(phone=phone, return_data=True, config=config, proxies=proxies, use_proxy=use_proxy)

async def claim_process(config, proxies):
    while True: 
        sessions = glob.glob(str(SESSION_FOLDER / "*.session"))
        for session in sessions:
            phone = Path(session).stem
            await telegram(phone=phone, return_data=True, config=config, proxies=proxies, use_proxy=config.get("use_proxy", False))
        
        auth_tokens = read_auth_tokens_from_file('data.txt')
        coin_limit = config.get("coin_limit", 5)
        use_proxy = config.get("use_proxy", False)
        
        with ThreadPoolExecutor(max_workers=len(auth_tokens)) as executor:
            futures = [executor.submit(process_account, auth_token, coin_limit, idx + 1, use_proxy, proxies) for idx, auth_token in enumerate(auth_tokens)]
            for future in futures:
                future.result()
        
        for i in range(10, 0, -1):
            logger.info(f"Complete, wait {i} second(s)...")
            time.sleep(1)
        logger.info("====================================================")
        logger.info("Wait for 10 minutes before repeating the loop")
        time.sleep(600) 

if __name__ == "__main__":
    try:
        config = read_config_from_file('config.json')
        proxies = read_proxies_from_file('proxies.txt')
        option = input("Choose mode: (1) Create session, (2) Run Claim process: ")
        if option == "1":
            asyncio.run(main_telegram(config, proxies))
        elif option == "2":
            asyncio.run(claim_process(config, proxies))
        else:
            logger.error("Invalid option")
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        exit()
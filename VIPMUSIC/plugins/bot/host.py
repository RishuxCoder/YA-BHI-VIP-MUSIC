import asyncio
import os
import socket
import requests
import urllib3
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyromod.exceptions import ListenerTimeout
from VIPMUSIC import app
from VIPMUSIC.misc import SUDOERS
from VIPMUSIC.utils.database import save_app_info
from VIPMUSIC.utils.pastebin import VIPbin

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEROKU_API_URL = "https://api.heroku.com"
HEROKU_API_KEY = os.getenv("HEROKU_API_KEY")  # Pre-defined variable
REPO_URL = "https://github.com/THE-VIP-BOY-OP/VIP-MUSIC"  # Pre-defined variable
BUILDPACK_URL = "https://github.com/heroku/heroku-buildpack-python"
UPSTREAM_REPO = "https://github.com/THE-VIP-BOY-OP/VIP-MUSIC"  # Pre-defined variable
UPSTREAM_BRANCH = "master"  # Pre-defined variable
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")


async def is_heroku():
    return "heroku" in socket.getfqdn()


async def paste_neko(code: str):
    return await VIPbin(code)


def fetch_app_json(repo_url):
    app_json_url = f"{repo_url}/raw/master/app.json"
    response = requests.get(app_json_url)
    return response.json() if response.status_code == 200 else None


def make_heroku_request(endpoint, api_key, method="get", payload=None):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json",
    }
    url = f"{HEROKU_API_URL}/{endpoint}"
    response = getattr(requests, method)(url, headers=headers, json=payload)
    return response.status_code, (
        response.json() if response.status_code == 200 else None
    )


async def fetch_apps():
    status, apps = make_heroku_request("apps", HEROKU_API_KEY)
    return apps if status == 200 else None


async def collect_env_variables(message, env_vars, app_name):
    user_inputs = {}
    await message.reply_text(
        "Provide the values for the required environment variables. Type /cancel at any time to cancel the deployment."
    )

    for var_name, var_info in env_vars.items():
        if var_name in [
            "HEROKU_APP_NAME",
            "HEROKU_API_KEY",
            "UPSTREAM_REPO",
            "UPSTREAM_BRANCH",
            "API_ID",
            "API_HASH",
        ]:
            continue  # Skip hardcoded variables

        # Get description from the JSON file
        description = var_info.get("description", "No description provided.")

        try:
            # Ask the user for input with the variable's description
            response = await app.ask(
                message.chat.id,
                f"Provide a value for **{var_name}**\n\n**About:** {description}\n\nType /cancel to stop hosting.",
                timeout=300,
            )
            if response.text == "/cancel":
                await message.reply_text("**Deployment canceled.**")
                return None
            user_inputs[var_name] = response.text
        except ListenerTimeout:
            await message.reply_text(
                "Timeout! You must provide the variables within 5 Minutes. Restart the process to deploy."
            )
            return None

    # Add hardcoded variables
    user_inputs["HEROKU_APP_NAME"] = app_name
    user_inputs["HEROKU_API_KEY"] = HEROKU_API_KEY
    user_inputs["UPSTREAM_REPO"] = UPSTREAM_REPO
    user_inputs["UPSTREAM_BRANCH"] = UPSTREAM_BRANCH
    user_inputs["API_ID"] = API_ID
    user_inputs["API_HASH"] = API_HASH

    return user_inputs


@app.on_message(filters.command("host") & filters.private & SUDOERS)
async def host_app(client, message):
    global app_name  # Declare global to use it everywhere

    # Ask the user whether to host in individual or team
    buttons = [
        [InlineKeyboardButton("Individual", callback_data="host_individual")],
        [InlineKeyboardButton("Team", callback_data="host_team")],
        [InlineKeyboardButton("Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    
    await message.reply_text(
        "Where do you want to host your app?",
        reply_markup=reply_markup
    )


@app.on_callback_query()
async def on_callback_query(client, callback_query):
    data = callback_query.data

    if data == "host_individual":
        await callback_query.message.edit_text("You are going to host your bot in individual Heroku.")
        await proceed_with_hosting(callback_query.message, "individual")

    elif data == "host_team":
        await list_teams(callback_query)

    elif data.startswith("team_"):
        team_name = data.split("_", 1)[1]
        await callback_query.message.edit_text(f"You are going to host your bot on team: {team_name}")
        await proceed_with_hosting(callback_query.message, team_name)

    elif data == "main_menu":
        await callback_query.message.edit_text("Back to main menu.")


async def list_teams(callback_query):
    # Fetch the list of teams from Heroku
    status, teams = make_heroku_request("teams", HEROKU_API_KEY)
    if not teams or status != 200:
        await callback_query.message.edit_text("Failed to fetch teams or no teams available.")
        return

    buttons = [[InlineKeyboardButton(team["name"], callback_data=f"team_{team['name']}")] for team in teams]
    buttons.append([InlineKeyboardButton("Back", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(buttons)

    await callback_query.message.edit_text("Select a team:", reply_markup=reply_markup)


async def proceed_with_hosting(message, host_type):
    app_json = fetch_app_json(REPO_URL)
    if not app_json:
        await message.reply_text("Could not fetch app.json.")
        return

    env_vars = app_json.get("env", {})
    app_name = f"{host_type}_app"  # Or ask user for app name as done previously

    user_inputs = await collect_env_variables(message, env_vars, app_name)
    if user_inputs is None:
        return

    # Now create the actual app with the selected name
    status, result = make_heroku_request(
        "apps",
        HEROKU_API_KEY,
        method="post",
        payload={"name": app_name, "region": "us", "stack": "container"},
    )
    if status == 201:
        await message.reply_text("✅ Done! Your app has been created.")

        # Set environment variables
        make_heroku_request(
            f"apps/{app_name}/config-vars",
            HEROKU_API_KEY,
            method="patch",
            payload=user_inputs,
        )

        # Trigger build
        status, result = make_heroku_request(
            f"apps/{app_name}/builds",
            HEROKU_API_KEY,
            method="post",
            payload={"source_blob": {"url": f"{REPO_URL}/tarball/master"}},
        )

        buttons = [
            [InlineKeyboardButton("Turn On Dynos", callback_data=f"dyno_on:{app_name}")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        if status == 201:
            ok = await message.reply_text("⌛ Deploying, please wait a moment...")
            await save_app_info(message.from_user.id, app_name)
            await asyncio.sleep(200)
            await ok.delete()
            await message.reply_text(
                "✅ Deployed Successfully...✨\n\n🥀 Please turn on dynos 👇",
                reply_markup=reply_markup,
            )
        else:
            await message.reply_text(f"Error triggering build: {result}")

    else:
        await message.reply_text(f"Error deploying app: {result}")
        
# ============================CHECK APP==================================#


@app.on_message(
    filters.command(["heroku", "hosts", "hosted", "mybots", "myhost"]) & SUDOERS
)
async def get_deployed_apps(client, message):
    apps = await fetch_apps()

    if not apps:
        await message.reply_text("No apps found on Heroku.")
        return

    buttons = [
        [InlineKeyboardButton(app["name"], callback_data=f"app:{app['name']}")]
        for app in apps
    ]

    buttons.append([InlineKeyboardButton("Back", callback_data="main_menu")])

    # Send the inline keyboard markup
    reply_markup = InlineKeyboardMarkup(buttons)

    await message.reply_text("Select an app:", reply_markup=reply_markup)


# ============================DELETE APP==================================#


@app.on_message(filters.command("deletehost") & filters.private & SUDOERS)
async def delete_deployed_app(client, message):
    # Fetch the list of deployed apps for the user
    user_apps = await fetch_apps()

    # Check if the user has any deployed apps
    if not user_apps:
        await message.reply_text("You have no deployed bots")
        return

    # Create buttons for each deployed app
    buttons = [
        [InlineKeyboardButton(app_name, callback_data=f"delete_app:{app_name}")]
        for app_name in user_apps
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    # Send a message to select the app for deletion
    await message.reply_text(
        "Please select the app you want to delete:", reply_markup=reply_markup
    )

"""
bot.py — Discloud entry point.

Discloud requires the main file to be in the project root.
This wrapper executes delivery/discord_bot.py as __main__ so
all its setup code and the if __name__ == "__main__": block run normally.
"""
import runpy

runpy.run_path("delivery/discord_bot.py", run_name="__main__")

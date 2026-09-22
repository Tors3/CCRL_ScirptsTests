@echo off
rem Unisce pgn\node*.pgn in results\all_games.pgn e calcola la classifica in results\
python "%~dp0merge_results.py" %*
pause

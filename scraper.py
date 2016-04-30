import logging
import random
import requests

from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from flask import Flask, jsonify, abort, request
from retrying import retry
from sets import Set

app = Flask(__name__)

endpoint = "http://j-archive.com"
banned_games = Set()

class JeopardyException(Exception):
    pass

class LinkClueException(JeopardyException):
    pass
    
class GameMissingException(JeopardyException):
    pass

class ClueMissingException(JeopardyException):
    pass

def get_latest_id():
    resp = requests.get(endpoint)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    footers = soup.findAll("td", { "class" : "splash_clue_footer" })
    return max(int(x.a['href'].split('=')[-1]) for x in footers)
    
def get_game(id):
    resp = requests.get("{0}/showgame.php".format(endpoint), params={'game_id': id})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    if soup.find("div", { "id": "jeopardy_round" }) is None or soup.find("div", { "id": "double_jeopardy_round" }) is None:
        banned_games.add(id)
        raise GameMissingException("Game does not exist")
    return soup
    
def get_categories(game, round):
    categories = game.findAll("td", { "class" : "category_name"})
    names = [x.text for x in categories]
    return names[(round-1)*6:round*6]
    
def get_question(game, round, category, value):
    clue = game.findAll("td", { "class" : "clue" })[(round - 1) * 30 + (category - 1) + (value - 1) * 6]
    if len(list(clue.children)) == 1:
        raise ClueMissingException("Clue does not exist")
    rows = clue.table.findChildren("tr", recursive=False)
    question = rows[1].td
    answer_mouseover = rows[0].td.div["onmouseover"]
    answer_text = answer_mouseover.split(",", 2)[2].strip("') ")
    soup = BeautifulSoup(answer_text, "html.parser")
    answer = soup.em.text
    
    if question.a is not None:
        raise LinkClueException("Question contains a link")
    return question.text, answer
    
def get_date(game):
    title = game.find("div", { "id": "game_title" })
    date_str = title.h1.text.split("-")[-1].strip()
    return date_str

def retry_if_jeopardy_error(exception):
    return isinstance(exception, JeopardyException)
    
@retry(retry_on_exception=retry_if_jeopardy_error, stop_max_attempt_number=5)
def get_random_clue_from_game(game):
    round = random.randint(1, 2)
    category = random.randint(1, 6)
    category_name = get_categories(game, round)[category - 1]
    value = random.randint(1,5)
    
    question, answer = get_question(game, round, category, value)
    
    return category_name, value, round, question, answer
    
def get_random_category_from_game(game, round):
    category = random.randint(1, 6)
    category_name = get_categories(game, round)[category - 1]
    questions, answers = zip(*[get_question(game, round, category, value) for value in range(1, 6)])
    return category_name, questions, answers
    
    
def get_random_game_id(max_game):
    id = None
    while id is None or id in banned_games:
        id = random.randint(1, max_game)
    return id

@retry(retry_on_exception=retry_if_jeopardy_error)
def get_random_clue(max_game):
    id = get_random_game_id(max_game)
    game = get_game(id)
    category_name, value, round, question, answer = get_random_clue_from_game(game)
    date = get_date(game)
    return category_name, value, id, round, question, answer, date
    
max_game = None
latest_update = datetime.now()

@retry(retry_on_exception=retry_if_jeopardy_error)
def get_random_category(max_game, round):
    id = get_random_game_id(max_game)
    game = get_game(id)
    category_name, questions, answers = get_random_category_from_game(game, round)
    date = get_date(game)
    return category_name, id, questions, answers, date
    
def update():
    global max_game
    global latest_update
    if max_game is None or datetime.now() - latest_update > timedelta(1):
        max_game = get_latest_id()
        latest_update = datetime.now()
    
@app.route("/")
def get_random():
    try:
        update()
        category_name, value, id, round, question, answer, date = get_random_clue(max_game)
        result = {"category": category_name, "value": value * 200 * round, "round": "Jeopardy" if round == 1 else "Double Jeopardy", "question": question, "answer": answer, "date": date }
        return jsonify(result)
    except Exception as ex:
        logging.error("An unexpected error occurred", exc_info=ex)
        abort(500)
        
@app.route("/category")
def get_category():
    try:
        round = request.args.get('round', None)
        round = int(round) if round is not None else random.randint(1, 2)
        update()
        category_name, id, questions, answers, date = get_random_category(max_game, round)
        result = {"category": category_name, "round": "Jeopardy" if round == 1 else "Double Jeopardy", "questions": questions, "answers": answers, "date": date }
        return jsonify(result)
    except Exception as ex:
        logging.error("An unexpected error occurred", exc_info=ex)
        abort(500)
    
        
        
# -*- coding: utf-8 -*-
"""
    MiniTwit
    ~~~~~~~~

    A microblogging application written with Flask and sqlite3.

    :copyright: (c) 2010 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""

import time
from sqlite3 import dbapi2 as sqlite3
from hashlib import md5
from datetime import datetime
from flask import Flask, request, session, url_for, redirect, \
     render_template, abort, g, flash, _app_ctx_stack
from werkzeug import check_password_hash, generate_password_hash

# configuration
DATABASE = '/tmp/mtu_acm.db'
DEBUG = True
SECRET_KEY = 'development key'

# create our little application :)
app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_envvar('MTU_ACM_SETTINGS', silent=True)

def get_db():
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    top = _app_ctx_stack.top
    if not hasattr(top, 'sqlite_db'):
        top.sqlite_db = sqlite3.connect(app.config['DATABASE'])
        top.sqlite_db.row_factory = sqlite3.Row
    return top.sqlite_db

@app.teardown_appcontext
def close_database(exception):
    """Closes the database again at the end of the request."""
    top = _app_ctx_stack.top
    if hasattr(top, 'sqlite_db'):
        top.sqlite_db.close()

def init_db():
    """Creates the database tables."""
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

def query_db(query, args=(), one=False):
    """Queries the database and returns a list of dictionaries."""
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv

def get_user_id(email):
    """Convenience method to look up the id for a username."""
    rv = query_db('select user_id from user where email = ?',
                  [email], one=True)
    return rv[0] if rv else None

def get_team_id(name):
    """Convenience method to look up the id for a team."""
    rv = query_db('select team_id from team where name = ?',
	    [name], one=True)
    return rv[0] if rv else None

def format_datetime(timestamp):
    """Format a timestamp for display."""
    return datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d @ %H:%M')

def gravatar_url(email, size=80):
    """Return the gravatar image for the given email address."""
    return 'http://www.gravatar.com/avatar/%s?d=identicon&s=%d' % \
        (md5(email.strip().lower().encode('utf-8')).hexdigest(), size)

@app.before_request
def before_request():
    g.user = None
    if 'user_id' in session:
        g.user = query_db('select * from user where user_id = ?',
                          [session['user_id']], one=True)

@app.route('/')
def home():
    """Displays the latest counts from all teams and users."""
    user_count = len(query_db("select * from user"))
    team_count = len(query_db("select * from team"))
    return render_template('home.html', user_count=user_count, team_count=team_count)

@app.route('/user/<int:user_id>', methods=['GET', 'POST'])
def user_profile(user_id):
    """Display's a users profile"""
    profile_user = query_db('select * from user where user_id = ?',
                            [user_id], one=True)

    if request.method == 'POST' and profile_user['user_id'] == g.user['user_id']:
	if 'shirtsize' in request.form:
	    db = get_db()
	    db.execute('''update user set shirt_size = ? where user_id = ?
		''', [request.form['shirtsize'], g.user['user_id']])
	    db.commit()
	return redirect(url_for('user_profile', user_id = g.user['user_id']))

    else:

	if profile_user['team_id'] != None:
	    profile_user_team = query_db('select * from team where team_id = ?',
		    [profile_user['team_id']], one=True)
	else:
	    profile_user_team = None

	if profile_user is None:
	    abort(404)
	if g.user:
	    # this is messy, I don't like always giving the template the shirt size
	    # but I guess we can always just check to see if g.user == profile_user and
	    # only display it if true
	    return render_template('profile.html', profile_user=profile_user,
		    profile_user_team=profile_user_team, shirt_size=profile_user['shirt_size'])
	else:
	    return redirect(url_for('home'))

@app.route('/team/<int:team_id>/delete', methods=['GET'])
def team_delete(team_id):
    team = query_db('select * from team where team_id = ?', [team_id], one=True)

    if g.user['user_id'] == team['admin_id']:
	db = get_db()
	db.execute('delete from team where team_id = ?', [team_id])
	db.execute('update user set team_id = ? where team_id = ?', [None, team_id])
	db.commit()
	flash("{team_name} has been deleted.".format(team_name=team['name']))
	return redirect(url_for('user_profile', user_id=g.user['user_id']))
    else:
	error = "You are not the administrator of this team."
	return render_template('team_profile', team_id=team_id, error=error)


@app.route('/team/<int:team_id>', methods=['GET'])
def team_profile(team_id):
    """Display's a teams profile page."""
    team = query_db('select * from team where team_id = ?', [team_id], one=True)
    members = query_db('select * from user where team_id = ?', [team_id])

    if team is None:
	abort(404)
    if g.user:
	return render_template('team_profile.html', team=team, members=members)
    else:
	return redirect(url_for('home'))

@app.route('/add_message', methods=['POST'])
def add_message():
    """Registers a new message for the user."""
    if 'user_id' not in session:
        abort(401)
    if request.form['text']:
        db = get_db()
        db.execute('''insert into message (author_id, text, pub_date)
          values (?, ?, ?)''', (session['user_id'], request.form['text'],
                                int(time.time())))
        db.commit()
        flash('Your message was recorded')
    return redirect(url_for('timeline'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Logs the user in."""
    if g.user:
        return redirect(url_for('user_profile', user_id=g.user.id))
    error = None
    if request.method == 'POST':
        user = query_db('''select * from user where
            email = ?''', [request.form['email']], one=True)
        if user is None:
            error = 'Invalid email'
        elif not check_password_hash(user['pw_hash'],
                                     request.form['password']):
            error = 'Invalid password'
        else:
            flash('You were logged in')
            session['user_id'] = user['user_id']
	    return redirect(url_for('user_profile', user_id=session['user_id']))
    return render_template('login.html', error=error)

@app.route('/team_register', methods=['GET', 'POST'])
def team_register():
    """Registers the team."""
    error = None

    teams = query_db('select * from team')
    join_team = len(teams) > 0

    if g.user['team_id'] is not None:
	flash("You are already signed up for a team!")
	return redirect(url_for('team_profile', team_id=g.user['team_id']))

    if not g.user:
	flash('You need to be logged in to do that!')
	return redirect(url_for('login'))

    if request.method == 'POST':

	hardware = 0
	create_team = False
	if not request.form['name']:
	    if not request.form['select_name']:
		error = 'You have to enter a valid team name'
		print teams
		return render_template('team_register.html', error=error, teams=teams, join_team=join_team)
	    else:
		name = request.form['select_name']
	else:
	    create_team = True
	    if 'hardware' in request.form:
		hardware = 1
	    name = request.form['name']

	db = get_db()
	flash_string = 'joined'
	team_id = get_team_id(name)
	if create_team:
	    if team_id is not None:
		error = 'That team name is already taken'
	    else:
		db.execute('''insert into team (name, admin_id, hardware) values
			(?, ?, ?)''', [name, g.user['user_id'], hardware])
		db.commit()
		flash_string = 'created'
		team_id = get_team_id(name) # gotta get team id so we can build url

	current_members = query_db('''select * from user where team_id = ?''', [team_id])

	if len(current_members) > 4:
	    error = '''{team_name} is currently full, please choose another team
		or create a new one.'''.format(team_name=name)
	    return render_template('team_register.html', error=error, teams=teams)
	else:
	    db.execute('''update user set team_id = ?
			    where user_id = ?''', [team_id, g.user['user_id']])
	    db.commit()
	    flash('''You successfully {flash_string} {team_name}!
		    '''.format(flash_string=flash_string, team_name=name))
	    return redirect(url_for('team_profile', team_id=team_id))

    return render_template('team_register.html', error=error, teams=teams, join_team=join_team)

@app.route('/users', methods=['GET'])
def all_users():
    users = query_db('select * from user')
    return render_template('users.html', users=users)

@app.route('/teams', methods=['GET'])
def all_teams():
    teams = query_db('select * from team')
    team_data = {}
    for team in teams:
	team_data[team] = len(query_db('''
	    select * from team where team_id = ?''', [team['team_id']]))
    return render_template('teams.html', teams=teams, team_data=team_data)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registers the user."""
    if g.user:
        return redirect(url_for('profile'))
    error = None
    if request.method == 'POST':
	if not request.form['name']:
	    error = 'You have to enter a valid name'
        elif not request.form['email'] or \
                 '@mtu.edu' not in request.form['email']:
            error = 'You have to enter a valid email address'
        elif not request.form['password']:
            error = 'You have to enter a password'
        elif request.form['password'] != request.form['password2']:
            error = 'The two passwords do not match'
        elif get_user_id(request.form['email']) is not None:
            error = 'The email is already registered'
	elif 'shirtsize' not in request.form:
	    error = 'You need to pick a t-shirt size!'
        else:
            db = get_db()
            db.execute('''insert into user (
              name, email, shirt_size, pw_hash) values (?, ?, ?, ?)''',
              [request.form['name'], request.form['email'], request.form['shirtsize'],
               generate_password_hash(request.form['password'])])
            db.commit()
            flash('You were successfully registered and are now logged in')
	    user = query_db('''select * from user where email = ?
		    ''', [request.form['email']], one=True)
            session['user_id'] = user['user_id']
            return redirect(url_for('home'))
    return render_template('register.html', error=error)

@app.route('/logout')
def logout():
    """Logs the user out."""
    flash('You were logged out')
    session.pop('user_id', None)
    return redirect(url_for('home'))

def possess(name):
    if name[-1] == 's':
	return ''.join([name, '\''])
    else:
	return ''.join([name, '\'s'])

# add some filters to jinja
app.jinja_env.filters['datetimeformat'] = format_datetime
app.jinja_env.filters['gravatar'] = gravatar_url
app.jinja_env.filters['possess'] = possess

if __name__ == '__main__':
    init_db()
    app.run()

from database_setup import Base, Restaurant, MenuItem, User
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask import session as login_session
import random, string

from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

app = Flask(__name__)

CLIENT_ID = json.loads(open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "RestaurantMenuApp"

### Create session and connect to database. ###
engine = create_engine('postgresql:///restaurantmenu.db')
Base.metadata.bind = engine
DBSession = sessionmaker(bind=engine)
session = DBSession()

### Anti forgery state token. ###
@app.route('/login/')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)

### Gconnect route. ###
@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    login_session['access_token'] = access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_credentials = login_session.get('credentials')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_credentials is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps('Current user is already connected.'),
                                 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['credentials'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    user_id = getUserID(data["email"])
    if not user_id:
        user_id = createUser(login_session)
        login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output

### Gdisconnect. ###
@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session['access_token']
    print 'In gdisconnect access token is %s', access_token
    print 'User name is: '
    print login_session['username']
    if access_token is None:
 	print 'Access Token is None'
    	response = make_response(json.dumps('Current user not connected.'), 401)
    	response.headers['Content-Type'] = 'application/json'
    	return response
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print 'result is '
    print result
    if result['status'] == '200':
	del login_session['access_token']
    	del login_session['gplus_id']
    	del login_session['username']
    	del login_session['email']
    	del login_session['picture']
    	response = make_response(json.dumps('Successfully disconnected.'), 200)
    	response.headers['Content-Type'] = 'application/json'
    	return response
    else:

    	response = make_response(json.dumps('Failed to revoke token for given user.', 400))
    	response.headers['Content-Type'] = 'application/json'
    return response

### User helper functions. ###
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None

### Show all restaurants. ###
@app.route('/')
@app.route('/restaurants/')
def showRestaurants():
    restaurants = session.query(Restaurant).all()
    return render_template('restaurants.html', restaurants=restaurants)

### Create new restaurant. ###
@app.route('/restaurant/new/',
            methods=['GET', 'POST'])
def newRestaurant():
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        newRestaurant = Restaurant(name=request.form['name'],
            user_id = login_session.get('user_id'))
        session.add(newRestaurant)
        flash('%s Successfully Created' % newRestaurant.name)
        session.commit()
        return redirect(url_for('showRestaurants'))
    else:
        return render_template('newRestaurant.html')

### Create new menu item. ###
@app.route('/restaurant/<int:restaurant_id>/menu/new/',
            methods=['GET', 'POST'])
def newMenuItem(restaurant_id):
    if 'username' not in login_session:
        return redirect('/login')
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    if request.method == 'POST':
        newMenuItem = MenuItem(name=request.form['name'],
                               description=request.form['description'],
                               price=request.form['price'],
                               user_id = login_session.get('user_id'),
                               restaurant_id=restaurant.id)
        session.add(newMenuItem)
        flash('%s Successfully Created' % newMenuItem.name)
        session.commit()
        return redirect(url_for('showMenu', restaurant_id=restaurant.id))
    else:
        return render_template('newMenuItem.html', restaurant=restaurant)

### Edit a restaurant. ###
@app.route('/restaurant/<int:restaurant_id>/edit/',
            methods=['GET', 'POST'])
def editRestaurant(restaurant_id):
    if 'username' not in login_session:
        return redirect('/login')
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    if restaurant.user_id != login_session.get('user_id'):
        return redirect(url_for('showRestaurants'))
    if request.method == 'POST':
        if request.form['newname']:
            restaurant.name = request.form['newname']
            flash('Restaurant Successfully Edited')
            return redirect(url_for('showRestaurants'))
    else:
        return render_template('editRestaurant.html', restaurant=restaurant)

### Edit a menu item. ###
@app.route('/restaurant/<int:restaurant_id>/menu/<int:menuitem_id>/edit/',
            methods=['GET', 'POST'])
def editMenuItem(menuitem_id, restaurant_id):
    if 'username' not in login_session:
        return redirect('/login')
    menuitem = session.query(MenuItem).filter_by(id=menuitem_id).one()
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    if menuitem.user_id != login_session.get('user_id'):
        return redirect(url_for('showMenu'))
    if request.method == 'POST':
        if request.form['name']:
            menuitem.name = request.form['name']
        if request.form['description']:
            menuitem.description = request.form['description']
        if request.form['price']:
            menuitem.price = request.form['price']
        session.add(menuitem)
        session.commit()
        flash('menu item succesfully edited')
        return redirect(url_for('showMenu', restaurant_id=menuitem.restaurant_id))
    else:
        return render_template('editMenuItem.html', menuitem=menuitem, restaurant=restaurant)

### Delete a restaurant. ###
@app.route('/restaurant/<int:restaurant_id>/delete/',
            methods=['GET', 'POST'])
def deleteRestaurant(restaurant_id):
    if 'username' not in login_session:
        return redirect('/login')
    dRestaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    if dRestaurant.user_id != login_session.get('user_id'):
        return redirect(url_for('showRestaurants'))
    if request.method == 'POST':
        session.delete(dRestaurant)
        session.commit()
        flash('restaurant succesfully deleted.')
        return redirect(url_for('showRestaurants', restaurant_id=restaurant_id))
    else:
        return render_template('deleteRestaurant.html', restaurant=dRestaurant)

### Delete an item. ###
@app.route('/restauarant/int:restaurant_id>/menu/<int:menuitem_id>/delete/',
            methods=['GET', 'POST'])
def deleteMenuItem(menuitem_id):
    if 'username' not in login_session:
        return redirect('/login')
    menuitem = session.query(MenuItem).filter_by(id=menuitem_id).one()
    if menuitem.user_id != login_session.get('user_id'):
        return redirect(url_for('showMenu'))
    if request.method == 'POST':
        session.delete(menuitem)
        session.commit()
        flash('menu item succesfully deleted.')
        return redirect(url_for('showMenu', restaurant_id=menuitem.restaurant_id))
    else:
        return render_template('deleteMenuItem.html', menuitem=menuitem)

### Show a restaurant menu. ###
@app.route('/restaurant/<int:restaurant_id>/')
@app.route('/restaurant/<int:restaurant_id>/menu/')
def showMenu(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    menuitems = session.query(MenuItem).filter_by(restaurant_id=restaurant_id).all()
    return render_template('menu.html', menuitems=menuitems, restaurant=restaurant)

### API Endpoints. ###
@app.route('/restaurant/JSON')
def restaurantsJSON():
    restaurants = session.query(Restaurant).all()
    return jsonify(Restaurant=[restaurant.serialize for restaurant in restaurants])

@app.route('/restaurant/<int:restaurant_id>/menu/JSON')
def restaurantMenuJSON(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    menuitems = session.query(MenuItem).filter_by(restaurant_id=restaurant_id).all()
    return jsonify(MenuItem=[menuitem.serialize for menuitem in menuitems])

@app.route('/restaurant/<int:restaurant_id>/menu/<int:menuitem_id>/JSON')
def menuItemJSON(restaurant_id, menuitem_id):
    menuitem = session.query(MenuItem).filter_by(id=menuitem_id).one()
    return jsonify(MenuItem=menuitem.serialize)

@app.route('/restaurant/<int:restaurant_id>/JSON')
def restaurantJSON(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    return jsonify(Restaurant=restaurant.serialize)

if __name__ == '__main__':
    app.debug = True
    app.secret_key = "Udacity is fun"
    app.run(host='0.0.0.0', port=5000)

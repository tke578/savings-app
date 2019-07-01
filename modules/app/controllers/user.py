import os
from flask import request, jsonify, redirect, url_for
from app import app, mongo
from app.schemas import validate_user, validate_saving, validate_saving_funds
import logger
import requests
import json
from functools import wraps

ROOT_PATH = os.environ.get('ROOT_PATH')
LOG = logger.get_root_logger(
    __name__, filename=os.path.join(ROOT_PATH, 'output.log'))


def oauth_required(f):
	@wraps(f)
	def wrap(*args, **kwargs):
		if 'oauth_key' not in request.headers:
			return jsonify({'ok': False, 'message': 'Missing oauth key!'}), 400
	return wrap


@app.route('/register', methods=['POST'])
def register():
	data = validate_user(request.get_json())
	
	if data['ok']:
		headers = {
					'X-SP-GATEWAY': os.environ.get('CLIENT_ID')+'|'+os.environ.get('CLIENT_SECRET'),
					'X-SP-USER-IP': '127.0.0.1',
					'X-SP-USER': '|e83cf6ddcf778e37bfe3d48fc78a6502062fca', #DEFAULT FINGERPRINT
					'Content-Type': 'application/json'
					}
		data = data['data']
		api_end_point = 'https://uat-api.synapsefi.com/v3.1/users'
		payload = {
				"logins": [
					{
					"email": data['email']
					}	
				],
				"phone_numbers": [
					data['phone_number']
				],
				"legal_names": [
					data['legal_name']
				]
			}
		headers['X-SP-GATEWAY'] = os.environ.get('CLIENT_ID')+'|'+os.environ.get('CLIENT_SECRET')
		response = requests.post(url=api_end_point, data=json.dumps(payload), headers=headers)

		if response.status_code == 200:
			mongo.db.users.insert_one(response.json())
			generate_oauth(response.json()['_id'], response.json()['refresh_token'])
			user = mongo.db.users.find_one({'_id': response.json()['_id']})
			msg = { 'oauth_key': user['oauth_key'], 'user_id': user['_id'] }
			return jsonify(msg), 200
		else:
			return jsonify(response.json()), 400
	else:
		return jsonify({'ok': False, 'message': 'Bad request parameters: {}'.format(data['message'])}), 400

# 		

def generate_oauth(user_id, refresh_token):
	api_end_point = 'https://uat-api.synapsefi.com/v3.1/oauth/'
	headers = {
					'X-SP-GATEWAY': os.environ.get('CLIENT_ID')+'|'+os.environ.get('CLIENT_SECRET'),
					'X-SP-USER-IP': '127.0.0.1',
					'X-SP-USER': '|e83cf6ddcf778e37bfe3d48fc78a6502062fca', #DEFAULT FINGERPRINT
					'Content-Type': 'application/json'
				}
	payload = { 'refresh_token': refresh_token }
	headers['X-SP-GATEWAY'] = os.environ.get('CLIENT_ID')+'|'+os.environ.get('CLIENT_SECRET')
	response = requests.post(url=api_end_point+'/'+user_id, data=json.dumps(payload), headers=headers)
	oauth_key = response.json()['oauth_key']
	mongo.db.users.update_one({"_id": user_id}, {'$set': { 'oauth_key': oauth_key}})


@app.route('/open_savings_account/<user_id>', methods=['POST'])
@oauth_required
def open_savings_account(user_id):	
	api_end_point = 'https://uat-api.synapsefi.com/v3.1/users/'+user_id+'/nodes'
	headers = {
				'X-SP-USER-IP': '127.0.0.1',
				'X-SP-USER': oauth_key+'|e83cf6ddcf778e37bfe3d48fc78a6502062fc', #DEFAULT FINGERPRINT
				'Content-Type': 'application/json'
	}
	data = validate_saving(request.get_json())
	if data['ok']:
		payload = { 
				"type": "IB-DEPOSIT-US",
				"info": data['data']
			}
		response = requests.post(url=api_end_point, data=json.dumps(payload), headers=headers)
		if response.json()['success'] == False:
			return jsonify(response.json())
		else:
			mongo.db.savings.insert_one(response.json()['nodes'][0])
			node_structure = response.json()['nodes'][0]
			response_account_obj = {
				"account_id": node_structure['_id'],
				"account_info": node_structure['info']
			}
			return jsonify(response_account_obj)
	else:
		return jsonify(response.json())

@app.route('/refresh_token/<user_id>', methods=['POST'])
def get_refresh(user_id):
	api_end_point = 'https://uat-api.synapsefi.com/v3.1/users/'
	headers = {
				'X-SP-GATEWAY': os.environ.get('CLIENT_ID')+'|'+os.environ.get('CLIENT_SECRET'),
				'X-SP-USER-IP': '127.0.0.1',
				'X-SP-USER': '|e83cf6ddcf778e37bfe3d48fc78a6502062fc', #DEFAULT FINGERPRINT
				'Content-Type': 'application/json'
	}
	response = requests.get(url=api_end_point+user_id, headers=headers)
	if response.status_code == 200:
		generate_oauth(response.json()['_id'], response.json()['refresh_token'])
		user = mongo.db.users.find_one({'_id': response.json()['_id']})
		msg = { 'oauth_key': user['oauth_key'], 'user_id': user['_id'] }
		return jsonify(msg), 200
	else:
		return jsonify(response.json()), 400
		
@app.route('/deposit_funds/<user_id>/nodes/<node_id>/trans', methods=['POST'])
@oauth_required
def deposit_funds(user_id, node_id):
	api_end_point = 'https://uat-api.synapsefi.com/v3.1/users/'+user_id+'/nodes/'+node_id+'/trans'
	oauth_key = request.headers['oauth_key']
	headers = {
				'X-SP-USER-IP': '127.0.0.1',
				'X-SP-USER': oauth_key+'|e83cf6ddcf778e37bfe3d48fc78a6502062fc', #DEFAULT FINGERPRINT
				'Content-Type': 'application/json'
	}
	data = validate_saving_funds(request.get_json())
	if data['ok']:
		data = data['data']
		payload = {
			"to": {
				"type": "IB-DEPOSIT-US",
				"id": data['receiving_account']
			},
			"amount": {
				"amount": data['amount'],
				"currency": "USD"
			},
			"extra": {
				"ip": "127.0.0.1"
			}
		}
		response = requests.post(url=api_end_point, data=json.dumps(payload), headers=headers)
		if response.status_code == 200:
			mongo.db.deposits.insert_one(response.json())
			node_structure = response.json()
			transaction_obj = {
				"transaction_id": node_structure["_id"],
				"amount": node_structure["amount"]["amount"],
				"currency": node_structure["amount"]["currency"],
				"sending_account": node_structure["from"],
				"receiving_account": node_structure["to"]
			}
			return jsonify(transaction_obj), 200		
		else:
			return jsonify(response.json())
	else:
		return jsonify({'ok': False, 'message': 'Bad request parameters: {}'.format(data['message'])}), 400



@app.route('/all_user_savings_accounts/<user_id>', methods=['GET'])
def all_user_savings_accounts(user_id):
	savings = mongo.db.savings.find({'user_id': user_id})
	if savings.count() > 0:
		collection = []
		for acct in savings:
			collection.append(acct)
		return jsonify(collection), 200
	else:
		return jsonify({'ok': True, 'message': 'No savings accounts found under that user'})


@app.route('/all_user_deposits/<node_id>', methods=['GET'])
def all_user_deposits(node_id):
	collection = []
	deposits = mongo.db.deposits.find({'to.id': node_id })
	if deposits.count() > 0:
		for dep in deposits:
			collection.append(dep)
		return jsonify(collection), 200
	else:
		return jsonify({'ok': True, 'message': 'No deposits found under that account'})

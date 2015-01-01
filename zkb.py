#!/Python27/python.exe
from __future__ import division
import time, json, requests, ConfigParser, itertools
from datetime import datetime
from throttle import RetryPolicy

flatten = itertools.chain.from_iterable

from zkb_exceptions import *

try:
#for live connections later
	CANSTOMP = True
except ImportError:
	CANSTOMP = False

conf = ConfigParser.ConfigParser()
conf.read(["init.ini", "init_local.ini"])

zkb_base_query = conf.get("ZKB","base_query")
query_limit = int(conf.get("ZKB","query_limit"))
subquery_limit = int(conf.get("ZKB","subquery_limit"))
retry_limit = int(conf.get("ZKB","retry_limit"))
default_sleep = int(conf.get("ZKB","default_sleep"))
User_Agent = conf.get("GLOBALS","user_agent")
logfile = conf.get("ZKB","logfile")
result_dumpfile = conf.get("ZKB","result_dumpfile")

sleepTime = query_limit/(24*60*60)

log = open (logfile, 'a+')

gzip_override=0

snooze_routine = conf.get("ZKB","snooze_routine")
query_mod = float(conf.get("ZKB","query_mod"))

acceptable_date_formats = ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y%m%d%H%M")
def dateValidator(value, format="%Y%m%d%H%M"):
	if value is None: return None
	for f in acceptable_date_formats:
		try:
			date = time.strptime(value, f)
		except ValueError:
			pass
		else:
			return time.strftime(format, date)
	raise InvalidDateFormat(value, acceptable_date_formats)

def singletonValidator(value):
	if value is None: return None
	if (isinstance(value, str) and value.isdigit()) or isinstance(value, int):
		return str(value)
	raise InvalidQueryValue(value, 'Value must be int or convertible to int.')

def idValidator(value):
	if value is None: return None
	if isinstance(value, int):
		vlist = [value]
	elif isinstance(value, str):
		vlist = value.split(',')
	elif isinstance(value, list):
		vlist = value
	if len(vlist) > subquery_limit: raise TooManyIDsRequested(value, subquery_limit)
	return ','.join(vv for vv in [singletonValidator(v) for v in vlist] if vv is not None)

def modValidator(value): return True if value else None

def orderValidator(value):
	if value is None: return None
	value = value.lower()
	if value in ('asc', 'desc'):
		return value
	raise InvalidQueryValue(value, "must be 'asc' or 'desc'")

def secondsValidator(value):
	if value is None: return None
	secs = int(value)
	if secs <= (86400 * 7): 
		return str(secs)
	raise InvalidQueryValue(value, "pastSeconds is limited to a max of 7 days.")

zkb_required = (
	"characterID", 
	"corporationID", 
	"allianceID", 
	"factionID", 
	"shipTypeID", 
	"groupID", 
	"solarSystemID", 
	"solo", 
	"w-space", 
	"warID", 
	"killID"
)

zkb_modifiers = (
	"kills",
	"losses",
	"w-space",
	"solo",
	"no-items",
	"no-attackers",
	"api-only",
	"xml",
	"pretty",
	"finalblow-only"
)

zkb_date_params = (
	"startTime",
	"endTime"
)

zkb_singleton_params = (
	'limit',
	'page',
	'year',
	'month',
	'week',
	'beforeKillID',
	'afterKillID',
	'killID',
	'warID',
	'iskValue'
)

zkb_id_params = (
	'characterID',
	'corporationID',
	'allianceID',
	'factionID',
	'shipTypeID',
	'groupID',
	'solarSystemID',
	'regionID'
)

zkb_unique_params = (
	('orderDirection', orderValidator),
	('pastSeconds', secondsValidator)
)

zkb_params = (
	(zkb_modifiers, modValidator),
	(zkb_date_params, dateValidator),
	(zkb_singleton_params, singletonValidator),
	(zkb_id_params, idValidator)
)

zkb_synonyms = { 
	'ship': 'shipTypeID',
	'shipID': 'shipTypeID',
	'shipType': 'shipTypeID',
	'character': 'characterID',
	'corporation': 'corporationID',
	'alliance': 'allianceID',
	'faction': 'factionID',
	'group': 'groupID',
	'system': 'solarSystemID',
	'systemID': 'solarSystemID',
	'solarSystem': 'solarSystemID',
	'region': 'regionID',
	'startDate': 'startTime',
	'endDate': 'endTime',
	'war': 'warID'
}

zkb_rest_parameters = dict(
	itertools.chain(
		flatten(zip(p, itertools.repeat(v)) for p, v in zkb_params), 
		zkb_unique_params
	)
)

class ZKBQuery(object):
	Base = zkb_base_query # the URI root
	Synonyms = zkb_synonyms # a dict of 'alternateName': 'canonicalName' pairs
	Parameters = zkb_rest_parameters # a dict of 'parameterName': validatorFunction pairs
	Modifiers = zkb_modifiers # a list of query parameters that don't take a value
	Required = zkb_required # a list of query parameters which you must have at least one of (not all are required)
			
	def __init__ (self, startDate, queryArgs=""):
		self.queryElements = {}
		self.queryModifiers = set()
		self.startDate = dateValidator(startDate, "%Y-%m-%d")
		self.startDateTime = datetime.strptime(self.startDate,"%Y-%m-%d")
		self.response = None
		self.parseQueryArgs(queryArgs)
		self.startTime(self.startDate)
		
	def parseQueryArgs(self, queryArgs):
		param = None
		for item in queryArgs.split('/'):
			if param is not None:
				self.validateAndSet(param, item)
				param = None
			elif item in self.Modifiers:
				self.validateAndSet(item, True)
			elif item:
				param = item
	
	def validateAndSet(self, name="", value=None):
		name = name.replace('_', '-')
		if name in self.Synonyms: name = self.Synonyms[name]
		if name not in self.Parameters:
			raise InvalidQueryParameter(name, sorted(self.Parameters.keys() + self.Synonyms.keys()))
		validator = self.Parameters[name]
		value = validator(value)
		if name in self.Modifiers:
			if value:
				self.queryModifiers.add(name)
			elif name in self.queryModifiers:
				self.queryModifiers.remove(name)
		else:
			if value is not None:
				self.queryElements[name] = value
			elif name in self.queryElements:
				self.queryElements.pop(name)
		return self

	def __getattr__(self, name):
		if name.startswith("_"):
			return object.__getattr__(self, name)
		return lambda v=True: self.validateAndSet(name=name, value=v)
		
	def __str__(self):
		query = [self.Base]
		query += sorted(self.queryModifiers)
		query += sorted("{0}/{1}".format(p, v) for p, v in self.queryElements.iteritems() if v is not None)
		query.append("")
		return "/".join(query)

	def is_valid(self):
		params = set(self.queryElements.keys()) | self.queryModifiers
		required = set(self.Required)
		return len(params & required) > 0

	def get_query(self):
		if self.is_valid():
			return str(self)
		raise TooFewRequiredParameters(str(self), self.Required)

	def __iter__(self):
		if 'beforeKillID' not in self.queryElements:
			self.beforeKillID(fetchLatestKillID(self.startDate))
		while True:
			# no try/except -- it is the responsibility of the caller to handle recovery
			single_query_JSON = self.fetch_one()
			if len(single_query_JSON) == 0: break

			beforeKillTime, beforeKillID = earliestKill(single_query_JSON)
			# result_JSON should be == single_query_JSON
			result_JSON = filter(lambda kill: killDateTime(kill) > self.startDateTime, single_query_JSON)
			if len(result_JSON) == 0: break

			yield result_JSON

			if beforeKillTime < self.startDateTime: break

			self.beforeKillID(beforeKillID)
		
	def fetch(self):
		return fetchResults(self)
	
	def fetch_one(self):
		return fetchResult(self.get_query())

def killDateTime(kill):
	return datetime.strptime(kill["killTime"],"%Y-%m-%d %H:%M:%S")
	
def latestKill(kill_list):
	return max( 
		(killDateTime(kill), int(kill["killID"])) 
			for kill in kill_list
	)

def earliestKill(kill_list):
	return min( 
		(killDateTime(kill), int(kill["killID"])) 
			for kill in kill_list
	)

def fetchResults(queryObj, joined_json = []):
	try:
		for result in queryObj:
			print queryObj
			joined_json += result
	except:
		print "Fatal exception, going down in flames"
		_dump_results(queryObj, joined_json)	#major failure, dump for restart
		raise
	return joined_json
	
def fetchResult(zkb_url, policy=RetryPolicy()):
	retry_ok = lambda: True
	while retry_ok():
		try:
			response = requests.get(zkb_url, headers={'User-Agent': User_Agent})
			if response.ok:
				return response.json()
			# policy will decide which server errors are recoverable
			retry_ok = policy.server_error(response)
		except Exception as e: 
			# Policy will decide which exceptions are recoverable
			retry_ok = policy.transport_exception(uri, e)

def fetchLatestKillID(start_date):
	kill_obj = ZKBQuery(start_date, "api-only/solo/kills/limit/1/").fetch_one()
	return int(kill_obj[0]["killID"])
	
def _snooze(http_header,multiplier=1):
	global query_limit, sleepTime
	
	try:
		query_limit  = int(http_header["X-Bin-Max-Requests"])
		request_used = int(http_header["X-Bin-Request-Count"])
	except KeyError as e:
		sleepTime = query_limit/(24*60*60)*multiplier
		return sleepTime
	sleepTime = 0
	if request_used/query_limit <= 0.5:
		return sleepTime
	elif request_used/query_limit > 0.9:
		sleepTime = query_limit/(24*60*60)*multiplier*2
		return sleepTime	
	elif request_used/query_limit > 0.75:
		sleepTime = query_limit/(24*60*60)*multiplier
		return sleepTime
	elif request_used/query_limit > 0.5:
		sleepTime = query_limit/(24*60*60)*multiplier*0.5
		return sleepTime
	else:
		sleepTime = query_limit/(24*60*60)*multiplier
		return sleepTime

def _hour2Snooze(http_header):
	snooze = default_sleep
	progress = 0
	try:
		allowance = int(http_header["X-Bin-Max-Requests"])
		
	except KeyError as e:
		print "WARNING: X-Bin-Max-Requests not defined in header"
		return default_sleep
	try:
		progress = int(http_header["X-Bin-Request-Count"])
	except KeyError as e:
		print "WARNING: X-Bin-Request-Count not defined in header"
	
	if (progress/allowance) > 0.65:
		if snooze == 0: snooze += 1
		snooze * 2
	elif (progress/allowance) > 0.80:
		if snooze == 0: snooze += 1
		snooze * 4
	elif (progress/allowance) > 0.90:
		if snooze == 0: snooze += 1
		snooze * 8
	
	if (allowance - progress) <= 10:	#emergency backoff
		print 'critical allowance: %s' % (allowance - progress)
		snooze = (3600/allowance) * 10
	return snooze	

def _snoozeSetter(http_header):
	global query_limit,snooze_timer
	
	try:
		query_limit = int(http_header["X-Bin-Max-Requests"])
	except KeyError as e:
		print "WARNING: http_header key 'X-Bin-Max-Requests' not found"
		query_limit = int(conf.get("ZKB","query_limit"))
		snooze_timer = query_limit/(24*60*60)	#requests per day
			
def _politeSnooze(http_header):
	global snooze_timer
	call_sleep = 0
	conn_allowance = int(http_header["X-Bin-Attempts-Allowed"])
	conn_reqs_used = int(http_header["X-Bin-Requests"])	
	conn_sleep_time= int(header["X-Bin-Seconds-Between-Request"])
	
	if (conn_reqs_used+1)==conn_allowance:
		time.sleep(conn_sleep_time)

def _hourlySnooze(http_header):
	#Designed to work with queries/hour rules
	snooze = default_sleep
	progress = 0
	try:
		allowance = int(http_header["X-Bin-Max-Requests"])
		
	except KeyError as e:
		print "WARNING: X-Bin-Max-Requests not defined in header"
		return default_sleep
	try:
		progress = int(http_header["X-Bin-Request-Count"])
	except KeyError as e:
		print "WARNING: X-Bin-Request-Count not defined in header"
	print 3600 / allowance
	print '%s:%s' % (progress, allowance)
	snooze = (3600 / allowance) * query_mod
	
	if (progress/allowance) > 0.65:
		snooze * 1.1
	elif (progress/allowance) > 0.80:
		snooze * 1.5
	elif (progress/allowance) > 0.90:
		snooze * 2
		
	return snooze

def _dump_results(queryObj,results_json):
	dump_obj = []
	dump_obj.append(str(queryObj))
	dump_obj.append(queryObj.startDate)
	for kill in results_json:
		dump_obj.append(kill)

	
	dump = open(result_dumpfile,'w')
	dump.write(json.dumps(dump_obj,indent=4))
	dump.close()

def crash_recovery():
	print "recovering from file"
	dump_obj = json.load(open(result_dumpfile))
	query_address = dump_obj.pop(0)
	query_startdate = dump_obj.pop(0)
	
	zkb_args = query_address.split(zkb_base_query)
	
	crashQuery = ZKBQuery(query_startdate,zkb_args)
	
	fetchResults(crashQuery,dump_obj)	#this isn't perfect.  Would prefer higher level control
	
def main():
	newQuery2 = ZKBQuery("2014-12-27","api-only/corporationID/1894214152/")
	
	#_crash_recovery()
	
	#newQuery.api_only
	#newQuery.characterID(628592330)
	#newQuery.losses
	
	print newQuery2
	#print newQuery2.queryElements["beforeKillID"]
	test_return = newQuery2.fetch()
	print len(test_return)
	
if __name__ == "__main__":
	main()	
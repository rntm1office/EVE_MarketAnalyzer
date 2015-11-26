import sys, gzip, StringIO, sys, math, os, getopt, time, json, socket
#from os import path, environ, getcwd
import urllib2
import httplib
import requests
import urllib
import MySQLdb 
#ODBC connector not supported on pi/ARM platform
from datetime import datetime, timedelta
import threading
import smtplib	#for emailing logs 

from ema_config import *
thread_exit_flag = False

db_con = None
db_cur = None

##### GLOBAL VARS #####
script_pid = ""
snapshot_table = ""


def writelog(pid, message, push_email=False):
	logtime = datetime.utcnow()
	logtime_str = logtime.strftime('%Y-%m-%d %H:%M:%S')
	
	logfile = "%s%s-cron_zkb" % (script_dir_path, pid)
	log_msg = "%s::%s\n" % (logtime_str,message)
	if(compressed_logging):
		with gzip.open("%s.gz" % logfile,'a') as myFile:
			myFile.write(log_msg)
	else:
		with open("%s.log" % logfile,'a') as myFile:
			myFile.write(log_msg)
		
	if(push_email and bool_email_init):	#Bad day case
		#http://stackoverflow.com/questions/10147455/trying-to-send-email-gmail-as-mail-provider-using-python
		SUBJECT = '''cron_zkb CRITICAL ERROR - %s''' % pid
		BODY = message
		
		EMAIL = '''\From: {email_source}\nTo: {email_recipients}\nSubject: {SUBJECT}\n\n{BODY}'''
		EMAIL = EMAIL.format(
			email_source = email_source,
			email_recipients = email_recipients,
			SUBJECT = SUBJECT,
			BODY = BODY
			)
		try:
			mailserver = smtplib.SMTP(email_server,email_port)
			mailserver.ehlo()
			mailserver.starttls()
			mailserver.login(email_username, email_secret)
			mailserver.sendmail(email_source, email_recipients.split(', '), EMAIL)
			mailserver.close()
			writelog(pid, "SENT email with critical failure to %s" % email_recipients, False)
		except:
			writelog(pid, "FAILED TO SEND EMAIL TO %s" % email_recipients, False)

			
def _initSQL(table_name, pid=script_pid):
	global db_con, db_cur
	
	db_con = MySQLdb.connect(
		host   = db_host,
		user   = db_user,
		passwd = db_pw,
		port   = db_port,
		db     = db_schema)
	db_cur = db_con.cursor()
	db_cur.execute('''SHOW TABLES LIKE \'%s\'''' % table_name)
	db_exists = len(db_cur.fetchall())
	if db_exists:
		writelog(pid, '%s.%s:\tGOOD' % (db_schema,table_name))
	else:	#TODO: add override command to avoid 'drop table' command 
		table_init = open(path.relpath('SQL/%s.mysql' % table_name) ).read()
		table_init_commands = table_init.split(';')
		try:
			for command in table_init_commands:
				db_cur.execute(command)
				db_con.commit()
		except Exception as e:
			#TODO: push critical errors to email log (SQL error)
			writelog(pid, '%s.%s:\tERROR: %s' % (db_schema, table_name, e[1]), True)
			sys.exit(2)
		writelog(pid, '%s.%s:\tCREATED' % (db_schema, table_name))
	db_cur.execute('''SHOW COLUMNS FROM `%s`''' % table_name)
	raw_headers = db_cur.fetchall()
	tmp_headers = []
	for row in raw_headers:
		tmp_headers.append(row[0])
	
	global table_header
	table_header = ','.join(tmp_headers)
	
def main():
	global snapshot_table
	table_cleanup = False
	global script_pid
	script_pid = str(os.getpid())
	print(script_pid)
	
	try:
		opts, args = getopt.getopt(sys.argv[1:],'h:l', ['cleanup','table_override='])
	except getopt.GetoptError as e:
		print str(e)
		print 'unsupported argument'
		sys.exit()
	for opt, arg in opts:
		if opt == '--optimize_table':
			table_cleanup = True
			writelog(pid, "Executing table cleanup" % snapshot_table)
		elif opt == '--table_override':
			snapshot_table = arg
			writelog(pid, "write table changed to: `%s`" % snapshot_table)
		else:
			assert False
	
if __name__ == "__main__":
	try:
		main()
	except KeyboardInterrupt:
		thread_exit_flag = True
		raise
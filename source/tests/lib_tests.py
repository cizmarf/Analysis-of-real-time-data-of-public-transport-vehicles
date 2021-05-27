# Code library for tests
import argparse

from database import Database

def drop_all_tables(database_name="vehicle_positions_test_database"):
	print('Dropping all tables in ' + database_name)

	database_connection = Database(database_name)

	database_connection.cursor.execute("SET FOREIGN_KEY_CHECKS=0;")

	database_connection.cursor.execute("TRUNCATE TABLE " + database_name + ".rides;")
	database_connection.cursor.execute("TRUNCATE TABLE " + database_name + ".stops;")
	database_connection.cursor.execute("TRUNCATE TABLE " + database_name + ".trip_coordinates;")
	database_connection.cursor.execute("TRUNCATE TABLE " + database_name + ".trips;")
	database_connection.cursor.execute("TRUNCATE TABLE " + database_name + ".headsigns;")
	database_connection.connection.commit()

	test_select = database_connection.execute_fetchall('SELECT * FROM trip_coordinates')

	assert len(test_select) == 0

	database_connection.cursor.execute("SET FOREIGN_KEY_CHECKS=1;")

	print('Drop done')

def get_args():
	parser = argparse.ArgumentParser()
	parser.add_argument("--static_data", default=True, type=bool, help="Fill with static data or dynamic real-time data.")
	parser.add_argument("--static_demo", default=False, type=bool,
						help="Use only if static data in use, time of insert sets now and wait 20 s for next file.")
	parser.add_argument("--update_time", default=20, type=int, help="Time to next request")
	parser.add_argument("--update_error", default=20, type=int, help="Update time if network error occurred")
	parser.add_argument("--thu_only", default=False, type=bool, )
	parser.add_argument("--clean_old", default=-1, type=int, help="Deletes all trips inactive for more than set minutes")
	args = parser.parse_args([] if "__file__" not in globals() else None)

	return args

def get_args_thu_only():
	parser = argparse.ArgumentParser()
	parser.add_argument("--static_data", default=True, type=bool, help="Fill with static data or dynamic real-time data.")
	parser.add_argument("--static_demo", default=False, type=bool,
						help="Use only if static data in use, time of insert sets now and wait 20 s for next file.")
	parser.add_argument("--update_time", default=20, type=int, help="Time to next request")
	parser.add_argument("--update_error", default=20, type=int, help="Update time if network error occurred")
	parser.add_argument("--clean_old", default=-1, type=int, help="Deletes all trips inactive for more than set minutes")
	parser.add_argument("--thu_only", default=True, type=bool,)
	args = parser.parse_args([] if "__file__" not in globals() else None)

	return args

def get_args_demo():
	args = get_args()
	args.static_demo = True
	return args

def get_args_live_demo():
	args = get_args()
	args.static_data = False
	return args
#!/usr/bin/env python3

# main controler of the project
# downloads all data and inserts it

import argparse
import asyncio
import logging
import time
import sys

import mysql.connector

import lib
from all_vehicle_positions import All_vehicle_positions, Static_all_vehicle_positions
from build_models import Build_models
from database import Database
from stops import Stops
from file_system import File_system
from two_stops_model import Two_stops_model


def estimate_delays(all_vehicle_positions: All_vehicle_positions, models):

	for vehicle in all_vehicle_positions.iterate_vehicles():

		# gets model from given set, if no model found uses linear model by default
		model = models.get(
			str(vehicle.last_stop or '') + "_" +
			str(vehicle.next_stop or '') +
			("_bss" if lib.is_business_day(vehicle.last_updated) else "_hol"),
			Two_stops_model.Linear_model(vehicle.stop_dist_diff))

		tuple_for_predict = vehicle.get_tuple_for_predict()

		# else it uses last stop delay, set in trips construction
		if tuple_for_predict is not None:
			vehicle.cur_delay = model.predict(*tuple_for_predict)


async def update_or_insert_trip(vehicle, database_connection, args):
	# Tries to get id_trip. If trip does not exist returns empty list else
	# returns list where first element is id_trip.
	try_id_trip = database_connection.execute_fetchall("""
		SELECT id_trip 
		FROM trips 
		WHERE trip_source_id = %s 
		LIMIT 1"""
		, (vehicle.trip_id,))

	# Trip found
	if len(try_id_trip) != 0:

		# extracts trip id
		vehicle.id_trip = try_id_trip[0][0]

		try:
			# the vehicle have not started its trip yet
			if vehicle.cur_delay is not None:

				# Updates database row of current trip and adds new record of historical data
				database_connection.execute_transaction_commit_rollback("""
					SELECT update_trip_and_insert_coordinates_if_changed(%s, %s, %s, %s, %s, %s, %s);""",
					vehicle.get_tuple_update_trip(args.static_demo))

		except IOError as e:
			logging.warning("Update trip failed " + str(vehicle.trip_id) + str(e))
			# raise Exception(e)

	# Trip not found
	else:
		# Chooses trip source file (demo/production)
		if args.static_data:
			try:
				vehicle.static_get_json_trip_file()

			# if file not found do not insert inconsistent data
			except FileNotFoundError:
				return
		else:
			await vehicle.get_async_json_trip_file()

		try:
			# tries insert the new trip and gets back its inner database id
			# it means to save headsign, historical data, trip itself and timetable
			# for data consistence protection those commands are wrapped by transaction
			database_connection.execute('START TRANSACTION;')

			vehicle.id_trip = database_connection.execute_fetchall("""
				SELECT insert_new_trip_to_trips_and_coordinates_and_return_id(%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
				vehicle.get_tuple_new_trip(args.static_demo))[0][0]

			Stops.insert_ride_by_trip(database_connection, vehicle)

			database_connection.commit() # COMMIT

			# Saves shape of current trip into specific folder
			vehicle.save_shape_file()

		# if any exception occurs rollback and save trip to blacklist
		except Exception as e:
			database_connection.rollback() # ROLLBACK

			if isinstance(e, mysql.connector.errors.IntegrityError):
				print(vehicle.trip_id + " has null delay last stop")
			else:
				logging.warning("Trip insertion failed:", e)

# creates async methods
# speed up downloading trip files
# database is protected because it does not use multithreading
async def process_async_vehicles(all_vehicle_positions, database_connection, args):

	gather = []

	# Iterates for all vehicles found in source file
	for vehicle in all_vehicle_positions.iterate_vehicles():
		try:
			gather.append(update_or_insert_trip(vehicle, database_connection, args))

		except Exception as e:
			logging.warning("Trip update failed " + vehicle.trip_id + ". Exception: " + str(e))

	# runs async functions
	await asyncio.gather(*gather)


def main(database_connection, args):

	# loads all models from model directory
	models = File_system.load_all_models()

	# For static data source only
	static_iterator = None
	if args.static_data:
		static_all_vehicle_positions = Static_all_vehicle_positions(args)
		static_iterator = static_all_vehicle_positions.static_get_all_vehicle_positions_json()

	# The main project loop
	while True:
		req_start = time.time()  # Time of beginning of a new iteration
		all_vehicle_positions = All_vehicle_positions()  # Class for managing source file data

		# Chooses source file (demo/production)
		if args.static_data:
			try:
				# reads data from directory of historical vehicles positions
				all_vehicle_positions.json_file = next(static_iterator)

			# this exception occurs in the end of program
			except StopIteration:
				break

		else:
			# downloads realtime data
			all_vehicle_positions.get_all_vehicle_positions_json()

		# Creates class for each trip in current source file
		all_vehicle_positions.construct_all_trips(database_connection)

		# estimate delays based on models created
		estimate_delays(all_vehicle_positions, models)

		# runs trips insertion and update
		# async uses for trip file downloading only
		asyncio.run(process_async_vehicles(all_vehicle_positions, database_connection, args))

		print(str(len(all_vehicle_positions.vehicles)) + ' vehicles processed in ' + str(time.time() - req_start) + ' seconds')

		# sleeps the remaining time (processing of all vehicles can take several seconds)
		# sleeps in production or demo else fills database as fast as possible
		# in an extreme case of processing lot of vehicles it can take more than maximum sleep time
		# if this occurs it keeps running the main loop and writes a warning message
		if args.static_demo or not args.static_data:
			time_to_sleep = args.update_time - (time.time() - req_start)
			if time_to_sleep > 0:
				time.sleep(time_to_sleep)
			else:
				logging.warning("Sleep failed")

if __name__ == "__main__":

	# options parsing and setting
	# for production set static_data and static_demo to false
	# updata_* says update interval, recommended 20 s
	# if clean old or build models set the main procedure is skipped
	# if running build_models make sure there is enough historical data in database
	# if static demo running it does not show all passing trips throw a stop correctly
	parser = argparse.ArgumentParser()
	parser.add_argument("--static_data", default=False, action='store_true',
		help="Fill with static data or dynamic real-time data.")
	parser.add_argument("--thu_only", default=False, action='store_true',
		help='If static data used it will fill the database with Thursday 20/2/2020 data only. For statistic purpose only.')
	parser.add_argument("--static_demo", default=False, action='store_true',
		help="Use only if static data in use, inserts static vehicle position data and wait 20 s for next file.")
	parser.add_argument("--update_time", default=20, type=int,
		help="Time to next request")
	parser.add_argument("--update_error", default=20, type=int,
		help="Update time if network error occurred")
	parser.add_argument("--clean_old", default=-1, type=int,
		help="Deletes all trips inactive for more than set minutes")
	parser.add_argument("--build_models", default=False, action='store_true',
		help="Rebuild all models")
	parser.add_argument("--database", default='vehicle_positions_test_database', type=str,
		help='Name of database to use')
	args = parser.parse_args([] if "__file__" not in globals() else None)

	database_connection = Database(args.database)

	# if clean old option is set
	if args.clean_old != -1:
		ids_to_delete = database_connection.execute_procedure_fetchall("delete_trips_older_than_and_return_their_trip_id", (args.clean_old,))
		for id in ids_to_delete:
			File_system.delete_file(File_system.all_shapes / (id[0] + '.shape'))
		sys.exit(0)

	# if build models option is set
	if args.build_models:
		bm = Build_models()
		bm.get_data()
		bm.main()

	# this runs the main project features

	main(database_connection, args)


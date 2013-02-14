'''
Created on Jan 6, 2013

@author: jostheim
'''
import pandas as pd
import numpy as np
import types
import dateutil
import datetime
from dateutil import tz
from multiprocessing import Pool
import os, sys
import random
import pickle
import pytz
from pytz import timezone
from flight_history_events import get_estimated_gate_arrival_string, get_estimated_runway_arrival_string
from sklearn.ensemble import RandomForestClassifier
from sklearn import cross_validation
import traceback

random.seed(0)
na_values = ["MISSING", "HIDDEN"]
do_not_convert_to_date = ["icao_aircraft_type_actual"]
global learned_class_name, actual_class, scheduled_class
actual_class = "actual_gate_arrival"
scheduled_class = "scheduled_gate_arrival"
learned_class_name = "gate_arrival_diff"
features_to_remove = ["actual_gate_arrival", "gate_arrival_diff", 'actual_gate_arrival_weekday', 'actual_gate_arrival_day', 'actual_gate_arrival_hour', 'actual_gate_arrival_minute']
#features_to_remove = ["actual_runway_arrival", "runway_arrival_diff", 'actual_runway_arrival_weekday', 'actual_runway_arrival_day', 'actual_runway_arrival_hour', 'actual_runway_arrival_minute']

flight_history_date_cols = ['published_departure','published_arrival','scheduled_gate_departure','actual_gate_departure','scheduled_gate_arrival','actual_gate_arrival','scheduled_runway_departure','actual_runway_departure','scheduled_runway_arrival','actual_runway_arrival']
metar_date_cols = ['date_time_issued']
taf_date_cols = ['bulletintimeutc','issuetimeutc','validtimefromutc','validtimetoutc']
taf_forecast_date_cols = ['forecasttimefromutc','forecasttimetoutc','timebecomingutc']
fbwindreport_date_cols = ['createdutc']
flight_history_events_date_cols = ['date_time_recorded']
asdi_root_date_cols = ['updatetimeutc','originaldepartureutc','estimateddepartureutc','originalarrivalutc','estimatedarrivalutc']
asdiposition_date_cols = ['received']
atscc_deicing_date_cols = ['capture_time','start_time','end_time','invalidated_time']
atscc_delay_date_cols = ['capture_time','start_time','end_time','invalidated_time']
atscc_ground_delay_date_cols = ['signature_time','effective_start_time','effective_end_time','invalidated_time','cancelled_time','adl_time','arrivals_estimated_for_start_time','arrivals_estimated_for_end_time']

def myround(x, base=5):
    return int(base * round(float(x)/base))

def parse_date_time(val):
    if str(val).lower().strip() not in na_values and str(val).lower().strip() != "nan":
        #'2012-11-12 17:30:00+00:00
        try:
            datetime_obj = dateutil.parser.parse(val)
            datetime_obj = datetime_obj.replace(tzinfo=timezone('UTC'))
            datetime_obj = datetime_obj.astimezone(timezone('UTC'))
            return datetime_obj
        except ValueError as e:
#            print e
            return np.nan
    else:
        return np.nan
#        return datetime.strptime(val, "%Y-%m-%dT%H:%M:%S")

def convert_dates(val):
    try:
        datetime_obj = dateutil.parser.parse(val)
        datetime_obj = datetime_obj.replace(tzinfo=timezone('UTC'))
        datetime_obj = datetime_obj.astimezone(timezone('UTC'))
        return datetime_obj
    except Exception as e:
        return val

def generate_cutoff_times(first_day, num_days, interval_beginning_hours_after_midnight_UTC = 14, interval_length = 12):
    first_day = pytz.utc.localize(first_day)
    cutoff_times = []
    for day in range(num_days):
        day_beginning = first_day + datetime.timedelta(days = day, hours=9)
        interval_beginning = first_day + datetime.timedelta(days = day, hours=interval_beginning_hours_after_midnight_UTC)
        cutoff_times.append(interval_beginning + datetime.timedelta(hours = random.uniform(0, interval_length)))
    return cutoff_times

def write_dataframe(name, df, store):
    store[name] = df

def read_dataframe(name, store, convert_dates_switch = True):
    return store[name]

#def write_dataframe(name, df, store):
#    ''' Write a set of keys to our store representing N columns each of a larger table '''
#    keys = {}
#    buffered = []
#    for i, col in enumerate(df.columns):
#        buffered.append(col)
#        if len(buffered) == 500:
#            keys["{0}_{1}".format(name, i)] = buffered
#            buffered = []
#    if len(buffered) > 0:
#        keys["{0}_{1}".format(name, i)] = buffered
#    print keys
#    store.append_to_multiple(keys, df, keys.keys()[0])
#    
#
#def read_dataframe(name, store):
#    ''' Read a set of keys from our store representing N columns each of a larger table
#     and then join the pieces back into the full table. '''
#    keys = []
#    i = 0
#    while True:
#        if "{0}_{1}".format(name, i) in store.keys():
#            keys.append("{0}_{1}".format(name, i))
#        else:
#            break
#        i += 1
#    return store.select_as_multiple(keys)

def get_column_type(series):
    dtype_tmp = None
    for ix, type_val in series.dropna().iteritems():
        if type_val is not np.nan and str(type_val) != "nan" and type_val is not None:
            dtype_tmp = type(type_val)
            return dtype_tmp

def cast_date_columns(df, date_cols):
#    for col in date_cols:
#        df[col] = pd.Series(df[col].values, dtype='M8[ns]')
#        print df[col].dtype
#    return df
    pass

def get_flight_history(data_prefix, data_rev_prefix, date_prefix, cutoff_time = None):
    codes_file = os.path.join(data_prefix, "Reference", "usairporticaocodes.txt")
    us_icao_codes = get_us_airport_icao_codes(codes_file)
    filename = "{0}{1}/{2}/FlightHistory/flighthistory.csv".format(data_prefix, data_rev_prefix, date_prefix)
    df = pd.read_csv(filename, index_col=0, parse_dates=[8,9,10,11,12,13,14,15,16,17], date_parser=parse_date_time, na_values=na_values)
    if cutoff_time is not None:
        # grabs flights eligible for test set
        df = df.select(lambda i: flight_history_row_in_test_set(df.ix[i], cutoff_time, us_icao_codes))
        # masks some of the data
        hide_flight_history_columns(df, cutoff_time)

    cast_date_columns(df, flight_history_date_cols)
    return df

def get_us_airport_icao_codes(codes_file):
    df = pd.read_csv(codes_file)
    return set(df["icao_code"])

def get_flight_history_date_columns_to_hide():
    """
    Returns a list of date columns with values that should be hidden based on the cutoff time.
    """
    flight_history_date_columns_to_hide = [
        "actual_gate_departure",
        "actual_gate_arrival",
        "actual_runway_departure",
        "actual_runway_arrival",
    ]

    return flight_history_date_columns_to_hide

def hide_flight_history_columns(df, cutoff_time):
    cols_to_mask = get_flight_history_date_columns_to_hide()
    rows_modified = 0
    for i in df.index:
        row_modified = False
        for col in cols_to_mask:
            if df[col][i] is np.nan:
                continue
            if df[col][i] <= cutoff_time:
                continue
            df[col][i] = np.nan
            row_modified = True
        if row_modified:
            rows_modified += 1

def get_departure_time(row):
    if row["published_departure"] != "MISSING":
        return row["published_departure"]
    if row["scheduled_gate_departure"] != "MISSING":
        return row["scheduled_gate_departure"]
    if row["scheduled_runway_departure"] != "MISSING":
        return row["scheduled_runway_departure"]
    return "MISSING"

def flight_history_row_in_test_set(row, cutoff_time, us_icao_codes):
    """
    This function returns True if the flight is in the air and it
    meets the other requirements to be a test row (continental US flight)
    """
    departure_time = get_departure_time(row)
    if departure_time is not np.nan and departure_time > cutoff_time:
        return False
    if row["actual_gate_departure"] is np.nan:
        return False
    if row["actual_runway_departure"] is np.nan:
        return False
    if row["actual_runway_departure"] is not np.nan and row["actual_runway_departure"] > cutoff_time:
        return False
    if row["actual_runway_arrival"] is np.nan:
        return False
    if row["actual_runway_arrival"] is not np.nan and row["actual_runway_arrival"] <= cutoff_time:
        return False
    if row["actual_gate_arrival"] is np.nan:
        return False
    if row["actual_gate_arrival"] is not np.nan and row["actual_runway_arrival"] is not np.nan and row["actual_gate_arrival"] < row["actual_runway_arrival"]:
        return False   
    if row["actual_runway_departure"] is not np.nan and row["actual_gate_departure"] is not np.nan and row["actual_runway_departure"] < row["actual_gate_departure"]:
        return False 
    if row["arrival_airport_icao_code"] not in us_icao_codes:
        return False
    if row["departure_airport_icao_code"] not in us_icao_codes:
        return False
    return True

def get_test_flight_history(data_prefix, data_rev_prefix, date_prefix):
    filename = "{0}{1}/{2}/FlightHistory/flighthistory.csv".format(data_prefix, data_rev_prefix, date_prefix)
    df = None
    if os.path.isfile(filename):
        df = pd.read_csv(filename, index_col=0, parse_dates=[8,9,10,11,12,13,14,15,16,17], date_parser=parse_date_time, na_values=na_values)
    return df

def get_test_flights_combined(data_prefix, data_rev_prefix, date_prefix):
    filename = "{0}{1}/test_flights_combined.csv".format(data_prefix, data_rev_prefix, date_prefix)
    df = None
    if os.path.isfile(filename):
        df = pd.read_csv(filename, index_col=0, parse_dates=[8,9,10,11,12,13,14,15,16,17], date_parser=parse_date_time, na_values=na_values)
    return df

def get_metar(prefix, data_prefix, data_rev_prefix, date_prefix, cutoff_time = None):
    filename = "{0}{1}/{2}/metar/flightstats_metarreports_combined.csv".format(data_prefix, data_rev_prefix, date_prefix)
    metar_df = pd.read_csv(filename, index_col=['metar_reports_id'], parse_dates=[2], date_parser=parse_date_time, na_values=na_values)
    if cutoff_time is not None:
        metar_df = metar_df[metar_df['date_time_issued'] < cutoff_time]
    cast_date_columns(metar_df, metar_date_cols)
    filename = "{0}{1}/{2}/metar/flightstats_metarpresentconditions_combined.csv".format(data_prefix, data_rev_prefix, date_prefix)
    metar_present_conditions_df = pd.read_csv(filename, index_col=['metar_reports_id'], na_values=na_values)
    del metar_present_conditions_df['id'] 
    filename = "{0}{1}/{2}/metar/flightstats_metarrunwaygroups_combined.csv".format(data_prefix, data_rev_prefix, date_prefix)
    metar_runway_groups_df = pd.read_csv(filename, index_col=['metar_reports_id'], na_values=na_values)
    del metar_runway_groups_df['id'] 
    filename = "{0}{1}/{2}/metar/flightstats_metarskyconditions_combined.csv".format(data_prefix, data_rev_prefix, date_prefix)
    metar_sky_conditions_df = pd.read_csv(filename, index_col=['metar_reports_id'], na_values=na_values)
    del metar_sky_conditions_df['id'] 
    metar_join = metar_present_conditions_df.join([metar_runway_groups_df, metar_sky_conditions_df])
    metar_df = metar_df.join(metar_join)
    
    grouped = metar_df.groupby("weather_station_code")
    groups = []
    i = 0
    for name, group in grouped:
        d = {}
    #   print "switching"
        d = {'weather_station_code':name}
        group = group.sort_index(by='date_time_issued')
        for k, row in enumerate(group.values):
            prefix1 = k
            if k == 0:
                prefix1 = "first"
            if k == len(group.values)-1:
                prefix1 = "last"
            for j, val in enumerate(row):
                if group.columns[j] != "weather_station_code":
                    d["{0}_{1}_{2}".format(prefix, prefix1, group.columns[j])] = val
        groups.append(d)
        i += 1
    tmp_df = pd.DataFrame(groups)
    tmp_df.set_index('weather_station_code', inplace=True, verify_integrity=True)
    return tmp_df

def get_taf(prefix, data_prefix, data_rev_prefix, date_prefix, cutoff_time=None):
    filename = "{0}{1}/{2}/otherweather/flightstats_taf.csv".format(data_prefix, data_rev_prefix, date_prefix)
    taf_df = pd.read_csv(filename, index_col=['tafid'], parse_dates=[8,9,10,11], date_parser=parse_date_time, na_values=["MISSING"])
    if cutoff_time is not None:
        taf_df = taf_df[taf_df['bulletintimeutc'] < cutoff_time]
    cast_date_columns(taf_df, taf_date_cols)
    filename = "{0}{1}/{2}/otherweather/flightstats_tafforecast.csv".format(data_prefix, data_rev_prefix, date_prefix)
    taf_forceast_df = pd.read_csv(filename, index_col=['tafforecastid'], parse_dates=[4,5,7], date_parser=parse_date_time, na_values=["MISSING"])
    filename = "{0}{1}/{2}/otherweather/flightstats_taficing.csv".format(data_prefix, data_rev_prefix, date_prefix)
    taf_icing_df = pd.read_csv(filename, na_values=["MISSING"])
    filename = "{0}{1}/{2}/otherweather/flightstats_tafsky.csv".format(data_prefix, data_rev_prefix, date_prefix)
    taf_sky_df = pd.read_csv(filename, na_values=["MISSING"])
    filename = "{0}{1}/{2}/otherweather/flightstats_taftemperature.csv".format(data_prefix, data_rev_prefix, date_prefix)
    taf_temperature_df = pd.read_csv(filename, na_values=["MISSING"])
    filename = "{0}{1}/{2}/otherweather/flightstats_tafturbulence.csv".format(data_prefix, data_rev_prefix, date_prefix)
    taf_turbulence_df = pd.read_csv(filename, na_values=["MISSING"])
    
    grouped = taf_icing_df.groupby('tafforecastid')
    groups = []
    i = 0
    for n, (name, group) in enumerate(grouped):
        dict = {}
    #   print "switching"
        dict = {'tafforecastid':int(name)}
        for k, row in enumerate(group.values):
    #        print row
            for j, val in enumerate(row):
                if group.columns[j] != "tafforecastid":
                    dict["taf_icing_{0}_{1}".format(k, group.columns[j])] = val
        groups.append(dict)
        i += 1
    taf_icing_flattened_df = pd.DataFrame(groups)
    taf_icing_flattened_df.set_index("tafforecastid", inplace=True, verify_integrity=True)
    
    
    grouped = taf_sky_df.groupby('tafforecastid')
    groups = []
    i = 0
    for n, (name, group) in enumerate(grouped):
        dict = {}
    #   print "switching"
        dict = {'tafforecastid':int(name)}
        for k, row in enumerate(group.values):
    #        print row
            for j, val in enumerate(row):
                if group.columns[j] != "tafforecastid":
                    dict["taf_forecast_{0}_{1}".format(k, group.columns[j])] = val
        groups.append(dict)
        i += 1
    taf_sky_flattened_df = pd.DataFrame(groups)
    taf_sky_flattened_df.set_index("tafforecastid", inplace=True, verify_integrity=True)
    
    
    grouped = taf_temperature_df.groupby('tafforecastid')
    groups = []
    i = 0
    for n, (name, group) in enumerate(grouped):
        dict = {}
    #   print "switching"
        dict = {'tafforecastid':int(name)}
        for k, row in enumerate(group.values):
    #        print row
            for j, val in enumerate(row):
                if group.columns[j] != "tafforecastid":
                    dict["taf_temperature_{0}_{1}".format(k, group.columns[j])] = val
        groups.append(dict)
        i += 1
    taf_temperature_flattened_df = pd.DataFrame(groups)
    taf_temperature_flattened_df.set_index("tafforecastid", inplace=True, verify_integrity=True)
    
    
    grouped = taf_turbulence_df.groupby('tafforecastid')
    groups = []
    i = 0
    for n, (name, group) in enumerate(grouped):
        dict = {}
    #   print "switching"
        dict = {'tafforecastid':int(name)}
        for k, row in enumerate(group.values):
    #        print row
            for j, val in enumerate(row):
                if group.columns[j] != "tafforecastid":
                    dict["taf_turbulence_{0}_{1}".format(k, group.columns[j])] = val
        groups.append(dict)
        i += 1
    taf_turbulence_df_flattened_df = pd.DataFrame(groups)
    taf_turbulence_df_flattened_df.set_index("tafforecastid", inplace=True, verify_integrity=True)
    
    taf_forceast_df = taf_forceast_df.join([taf_icing_flattened_df, taf_sky_flattened_df, taf_temperature_flattened_df, taf_turbulence_df_flattened_df])
    grouped = taf_forceast_df.groupby('tafid')
    groups = []
    i = 0
    for n, (name, group) in enumerate(grouped):
        dict = {}
    #   print "switching"
        dict = {'tafid':int(name)}
        group = group.sort_index(by="forecasttimefromutc")
        for k, row in enumerate(group.values):
    #        print row
            for j, val in enumerate(row):
                if group.columns[j] != "tafid":
                    dict["{0}_{1}".format(k, group.columns[j])] = val
        groups.append(dict)
        i += 1
    taf_forceast_df_flattened = pd.DataFrame(groups)
    taf_forceast_df_flattened.set_index('tafid', inplace=True, verify_integrity=True)
    
    
    taf_df = taf_df.join(taf_forceast_df_flattened)
    
    grouped = taf_df.groupby('airport')
    groups = []
    i = 0
    for n, (name, group) in enumerate(grouped):
        dict = {}
    #   print "switching"
        dict = {'airport':name}
        group = group.sort_index(by="validtimefromutc")
        for k, row in enumerate(group.values):
    #        print row
            for j, val in enumerate(row):
                if group.columns[j] != "airport":
                    dict["{0}_{1}".format(k, group.columns[j])] = val
        groups.append(dict)
        i += 1
    
    taf_df = pd.DataFrame(groups)
    taf_df.set_index("airport", inplace=True, verify_integrity=True)
    new_col_names = []
    for col in taf_df.columns:
        new_col_names.append("{0}_{1}".format(prefix, col))
    taf_df.columns = new_col_names
    return taf_df

def get_fbwind(prefix, data_prefix, data_rev_prefix, date_prefix, cutoff_time=None):
    filename = "{0}{1}/{2}/otherweather/flightstats_fbwindreport.csv".format(data_prefix, data_rev_prefix, date_prefix)
    fbwindreport_df = pd.read_csv(filename, parse_dates=[1], date_parser=parse_date_time, na_values=na_values)
    if cutoff_time is not None:
        fbwindreport_df = fbwindreport_df[fbwindreport_df['createdutc'] < cutoff_time]
    cast_date_columns(fbwindreport_df, fbwindreport_date_cols)
    filename = "{0}{1}/{2}/otherweather/flightstats_fbwindairport.csv".format(data_prefix, data_rev_prefix, date_prefix)
    fbwindairport_df = pd.read_csv(filename, na_values=na_values)
    filename = "{0}{1}/{2}/otherweather/flightstats_fbwind.csv".format(data_prefix, data_rev_prefix, date_prefix)
    fbwind_df = pd.read_csv(filename, na_values=na_values)
    filename = "{0}{1}/{2}/otherweather/flightstats_fbwindaltitude.csv".format(data_prefix, data_rev_prefix, date_prefix)
    fbwindaltitude_df = pd.read_csv(filename, na_values=na_values)
    grouped = fbwindaltitude_df.groupby('fbwindreportid')
    groups = []
    i = 0
    for name, group in grouped:
        d = {}
    #   print "switching"
        d = {'fbwindreportid':int(name)}
        group = group.sort_index(by="ordinal")
        for k, row in enumerate(group.values):
    #        print row
            for j, val in enumerate(row):
                if group.columns[j] != "fbwindreportid" and group.columns[j] != "ordinal":
                    d["{0}_{1}".format(k, group.columns[j])] = val
        groups.append(d)
        i += 1
    fbwindaltitude_flattened_df = pd.DataFrame(groups)
    grouped = fbwind_df.groupby('fbwindairportid')
    groups = []
    i = 0
    for name, group in grouped:
        d = {}
    #   print "switching"
        d = {'fbwindairportid':int(name)}
        group = group.sort_index(by="ordinal")
        for k, row in enumerate(group.values):
    #        print row
            for j, val in enumerate(row):
                if group.columns[j] != "fbwindairportid" and group.columns[j] != "ordinal":
                    d["{0}_{1}".format(k, group.columns[j])] = val
        groups.append(d)
        i += 1
    fbwind_flattened_df = pd.DataFrame(groups)

    fbwind_joined = pd.merge(fbwindairport_df, fbwind_flattened_df, how="left", left_on="fbwindairportid", right_on="fbwindairportid")
    
    fbwindreport_df_joined = pd.merge(fbwindreport_df, fbwindaltitude_flattened_df, how="left", left_on="fbwindreportid", right_on="fbwindreportid")
    fbwindreport_df_joined.set_index("fbwindreportid", inplace=True, verify_integrity=True)
    
    fb_wind_df = pd.merge(fbwind_joined, fbwindreport_df_joined, how="left", left_on='fbwindreportid', right_index=True)
    del fb_wind_df['fbwindreportid']
    del fb_wind_df['fbwindairportid']
    
    grouped = fb_wind_df.groupby('airportcode')
    groups = []
    i = 0
    for name, group in grouped:
        d = {}
    #   print "switching"
        d = {'airportcode':name}
        group = group.sort_index(by="createdutc")
        for k, row in enumerate(group.values):
    #        print row
            for j, val in enumerate(row):
                if group.columns[j] != "airportcode":
                    d["{0}_{1}".format(k, group.columns[j])] = val
        groups.append(d)
        i += 1
    fbwind_df = pd.DataFrame(groups)
    fbwind_df.set_index("airportcode", inplace=True, verify_integrity=True)
    new_col_names = []
    for col in fb_wind_df.columns:
        new_col_names.append("{0}_{1}".format(prefix, col))
    fb_wind_df.columns = new_col_names
    return fb_wind_df

def parse_estimated_gate_arrival(val, offset):
    if val is None or val is np.nan or str(val) == "nan":
        return None
    estimated_gate_arrival = get_estimated_gate_arrival_string(val)
    if estimated_gate_arrival is not None:
        if offset>0:
            offset_str = "+" + str(offset)
        else:
            offset_str = str(offset)
        datetime_obj = dateutil.parser.parse(estimated_gate_arrival+offset_str)
        return datetime_obj
    return None

def parse_estimated_runway_arrival(val, offset):
    if val is None or val is np.nan or str(val) == "nan":
        return None
    estimated_runway_arrival = get_estimated_runway_arrival_string(val)
    if estimated_runway_arrival is not None:
        if offset>0:
            offset_str = "+" + str(offset)
        else:
            offset_str = str(offset)
        datetime_obj = dateutil.parser.parse(estimated_runway_arrival+offset_str)
        return datetime_obj
    return None


def get_flight_history_events(flight_history_df, data_prefix, data_rev_prefix, date_prefix, cutoff_time=None):
    events_filename = "{0}{1}/{2}/FlightHistory/flighthistoryevents.csv".format(data_prefix, data_rev_prefix, date_prefix)
    events_df = pd.read_csv(events_filename, na_values=na_values, parse_dates=[1], date_parser=parse_date_time)
    if cutoff_time is not None:
        events_df = events_df[events_df['date_time_recorded'] < cutoff_time]
    cast_date_columns(events_df, flight_history_events_date_cols)
    events_df["estimated_gate_arrival"] = np.nan
    events_df["estimated_runway_arrival"] = np.nan
    
    for ix, row in events_df.iterrows():
        if ix not in flight_history_df.index:
            continue
        if type(row["data_updated"]) != str:
            continue
        fh_row = flight_history_df.ix[ix]
        estimated_gate_arrival = parse_estimated_gate_arrival(row["data_updated"], fh_row['arrival_airport_timezone_offset'])
        estimated_runway_arrival = parse_estimated_runway_arrival(row['data_updated'], fh_row['arrival_airport_timezone_offset'])
        events_df["estimated_gate_arrival"][ix] = estimated_gate_arrival
        events_df["estimated_runway_arrival"][ix] = estimated_runway_arrival
        
    grouped = events_df.groupby("flight_history_id")
    groups = []
    i = 0
    for name, group in grouped:
        d = {}
        d = {'flight_history_id':int(name)}
        group = group.sort_index(by='date_time_recorded')
        for k, row in enumerate(group.values):
            prefix = k
            if k == 0:
                prefix = "first"
            if k == len(group.values)-1:
                prefix = "last"
            for j, val in enumerate(row):
                if group.columns[j] != "flight_history_id":
                    d["{0}_{1}".format(prefix, group.columns[j])] = val
        groups.append(d)
        i += 1
    tmp_df = pd.DataFrame(groups)
    tmp_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    return tmp_df

def get_asdi_root(data_prefix, data_rev_prefix, date_prefix): 
    asdi_root_filename = "{0}{1}/{2}/ASDI/asdiflightplan.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_root_df = pd.read_csv(asdi_root_filename, na_values=na_values, index_col=['asdiflightplanid'], parse_dates=[1,7,8,9,10], date_parser=parse_date_time)
    asdi_root_df['estimateddepartureutc_diff'] = asdi_root_df['estimateddepartureutc'] - asdi_root_df['originaldepartureutc'] 
    asdi_root_df['estimateddepartureutc_diff'] =  asdi_root_df['estimateddepartureutc_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
    asdi_root_df['estimatedarrivalutc_diff'] = asdi_root_df['estimatedarrivalutc'] - asdi_root_df['originalarrivalutc'] 
    asdi_root_df['estimatedarrivalutc_diff'] =  asdi_root_df['estimatedarrivalutc_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
    return asdi_root_df

def get_asdi_airway(data_prefix, data_rev_prefix, date_prefix):
    asdi_airway_filename = "{0}{1}/{2}/ASDI/asdiairway.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_airway_df = pd.read_csv(asdi_airway_filename, index_col=['asdiflightplanid','ordinal'], na_values=na_values)
    return asdi_airway_df

def get_asdi_fpcenter(data_prefix, data_rev_prefix, date_prefix):
    asdi_asdifpcenter_filename = "{0}{1}/{2}/ASDI/asdifpcenter.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpcenter_df = pd.read_csv(asdi_asdifpcenter_filename, index_col=['asdiflightplanid','ordinal'], na_values=na_values)
    return asdi_asdifpcenter_df

def get_asdi_pfix(data_prefix, data_rev_prefix, date_prefix):
    asdi_asdifpfix_filename = "{0}{1}/{2}/ASDI/asdifpfix.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpfix_df = pd.read_csv(asdi_asdifpfix_filename, index_col=['asdiflightplanid','ordinal'], na_values=na_values)
    return asdi_asdifpfix_df

def get_asdi_psector(data_prefix, data_rev_prefix, date_prefix):
    asdi_asdifpsector_filename = "{0}{1}/{2}/ASDI/asdifpsector.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpsector_df = pd.read_csv(asdi_asdifpsector_filename, index_col=['asdiflightplanid','ordinal'], na_values=na_values)
    return asdi_asdifpsector_df

def get_asdi_waypoint(data_prefix, data_rev_prefix, date_prefix):
    asdi_asdifpwaypoint_filename = "{0}{1}/{2}/ASDI/asdifpwaypoint.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpwaypoint_df = pd.read_csv(asdi_asdifpwaypoint_filename, index_col=['asdiflightplanid','ordinal'], na_values=na_values)
    return asdi_asdifpwaypoint_df

def get_asdi_disposition(data_prefix, data_rev_prefix, date_prefix, cutoff_time=None):
    asdi_asdiposition_filename = "{0}{1}/{2}/ASDI/asdiposition.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdiposition_df = pd.read_csv(asdi_asdiposition_filename, parse_dates=[0], date_parser=parse_date_time, na_values=na_values)
    if cutoff_time is not None:
        asdi_asdiposition_df = asdi_asdiposition_df[asdi_asdiposition_df['received'] < cutoff_time]
    cast_date_columns(asdi_asdiposition_df, asdiposition_date_cols)
    grouped = asdi_asdiposition_df.groupby('flighthistoryid')
    groups = []
    i = 0
    for name, group in grouped:
        d = {}
    #   print "switching"
        d = {'flight_history_id':int(name)}
        group = group.sort_index(by='received')
        for k, row in enumerate(group.values):
            prefix = k
            if k == 0:
                prefix = "first"
            if k == len(group.values)-1:
                prefix = "last"
            for j, val in enumerate(row):
                if group.columns[j] != "flighthistoryid":
                    d["{0}_{1}".format(prefix, group.columns[j])] = val
        groups.append(d)
        i += 1
    tmp_df = pd.DataFrame(groups)
    tmp_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    return tmp_df

def get_asdi_merged(data_prefix, data_rev_prefix, date_prefix, cutoff_time=None):
    asdi_root_df = get_asdi_root(data_prefix, data_rev_prefix, date_prefix)
    if cutoff_time is not None:
        asdi_root_df = asdi_root_df[asdi_root_df['updatetimeutc'] < cutoff_time]
    asdi_airway_df = get_asdi_airway(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpcenter_df = get_asdi_fpcenter(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpfix_df = get_asdi_pfix(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpsector_df = get_asdi_psector(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpwaypoint_df = get_asdi_waypoint(data_prefix, data_rev_prefix, date_prefix)
    tmp = asdi_airway_df.join([asdi_asdifpcenter_df, asdi_asdifpfix_df, asdi_asdifpsector_df, asdi_asdifpwaypoint_df])
    grouped = tmp.groupby(level='asdiflightplanid')
    groups = []
    i = 0
    
    for name, group in grouped:
        d = {}
    #   print "switching"
        #print group.index[n]
        #group = group.sort_index(by='ordinal')
        for k, row in enumerate(group.values):
            prefix = group.index[k][1]
            if k == 0:
                prefix = "first"
            if k == len(group.values)-1:
                prefix = "last"
            for j, val in enumerate(row):
                if "asdiflightplanid" not in d:
                    d["asdiflightplanid"] = group.index[k][0]
                if group.columns[j] != "asdiflightplanid":
                    d["{0}_{1}".format(prefix, group.columns[j])] = val
        groups.append(d)
        i += 1
    tmp_df = pd.DataFrame(groups)
    tmp_df.set_index('asdiflightplanid', inplace=True, verify_integrity=True)
    asdi_merged_df = pd.merge(asdi_root_df, tmp_df, how="left", left_index=True, right_index=True)
    return asdi_merged_df

def get_atscc_deicing(data_prefix, data_rev_prefix, date_prefix, cutoff_time=None):
    atsccdeicing_filename = "{0}{1}/{2}/atscc/flightstats_atsccdeicing.csv".format(data_prefix, data_rev_prefix, date_prefix)
    atsccdeicing_df = None
    try:
        atsccdeicing_df = pd.read_csv(atsccdeicing_filename, index_col=[0], na_values=na_values, parse_dates=[1,2,3,4], date_parser=parse_date_time)
    except:
        print "deicing error, returning none", date_prefix
        return atsccdeicing_df
    if cutoff_time is not None:
        atsccdeicing_df = atsccdeicing_df[atsccdeicing_df['capture_time'] < cutoff_time]
        for ix in atsccdeicing_df[atsccdeicing_df['end_time'] > cutoff_time].index:
            atsccdeicing_df.ix[ix]["end_time"] = np.nan
        for ix in atsccdeicing_df[atsccdeicing_df['invalidated_time'] > cutoff_time].index:
            atsccdeicing_df.ix[ix]["invalidated_time"] = np.nan
    cast_date_columns(atsccdeicing_df, atscc_deicing_date_cols)
    end_time = []
    for ix,row in atsccdeicing_df.iterrows():
        end = row['end_time']
        if (end is None or end is np.nan ) or (row['invalidated_time'] is not None and row['invalidated_time'] is not np.nan and row['invalidated_time'] < end):
            end = row['invalidated_time']
        end_time.append(end)
    atsccdeicing_df['actual_end_time'] = pd.Series(end_time, index=atsccdeicing_df.index)
    return atsccdeicing_df

def get_atscc_delay(data_prefix, data_rev_prefix, date_prefix, cutoff_time=None):
    atsccdelay_filename = "{0}{1}/{2}/atscc/flightstats_atsccdelay.csv".format(data_prefix, data_rev_prefix, date_prefix)
    atsccdelay_df = pd.read_csv(atsccdelay_filename, index_col=[0], na_values=na_values, parse_dates=[1,2,3,4], date_parser=parse_date_time)
    if cutoff_time is not None:
        atsccdelay_df = atsccdelay_df[atsccdelay_df['capture_time'] < cutoff_time]
        for ix in atsccdelay_df[atsccdelay_df['end_time'] > cutoff_time].index:
            atsccdelay_df.ix[ix]['end_time'] = np.nan
        for ix in atsccdelay_df[atsccdelay_df['invalidated_time'] > cutoff_time].index:
            atsccdelay_df.ix[ix]['invalidated_time'] = np.nan
    cast_date_columns(atsccdelay_df, atscc_delay_date_cols)
    end_time = []
    for ix,row in atsccdelay_df.iterrows():
        end = row['end_time']
        if (end is None or end is np.nan) or (row['invalidated_time'] is not None and row['invalidated_time'] is not np.nan and row['invalidated_time'] < end):
            end = row['invalidated_time']
        end_time.append(end)
    atsccdelay_df['actual_end_time'] = pd.Series(end_time, index=atsccdelay_df.index)
    return atsccdelay_df

def get_atscc_ground_delay(data_prefix, data_rev_prefix, date_prefix, cutoff_time=None):
    atsccgrounddelay_filename = "{0}{1}/{2}/atscc/flightstats_atsccgrounddelay.csv".format(data_prefix, data_rev_prefix, date_prefix)
    atsccgrounddelay_df = pd.read_csv(atsccgrounddelay_filename, index_col=[0], na_values=na_values, parse_dates=[1,2,3,4,5,9,10,11], date_parser=parse_date_time)
    if cutoff_time is not None:
        atsccgrounddelay_df = atsccgrounddelay_df[atsccgrounddelay_df['effective_start_time'] < cutoff_time]
        for ix in atsccgrounddelay_df[atsccgrounddelay_df['invalidated_time'] > cutoff_time].index: 
            atsccgrounddelay_df.ix[ix]["invalidated_time"] = np.nan
        for ix in atsccgrounddelay_df[atsccgrounddelay_df['cancelled_time'] > cutoff_time].index:
            atsccgrounddelay_df.ix[ix]["cancelled_time"] = np.nan
    cast_date_columns(atsccgrounddelay_df, atscc_ground_delay_date_cols)
    atsccgrounddelayairports_filename = "{0}{1}/{2}/atscc/flightstats_atsccgrounddelayairports.csv".format(data_prefix, data_rev_prefix, date_prefix)
    atsccgrounddelayairports_df = pd.read_csv(atsccgrounddelayairports_filename, na_values=na_values)
    grouped = atsccgrounddelayairports_df.groupby('ground_delay_program_id')
    groups = []
    i = 0
    for name, group in grouped:
        d = {}
    #   print "switching"
        d = {'ground_delay_program_id':int(name)}
        for k, row in enumerate(group.values):
            for j, val in enumerate(row):
                if group.columns[j] != "ground_delay_program_id":
                    d["{0}_{1}".format(k, group.columns[j])] = val
        groups.append(d)
        i += 1
    if len(groups) == 0:
        return None
    atsccgrounddelayairports_tmp_df = pd.DataFrame(groups)
    atsccgrounddelayairports_tmp_df.set_index('ground_delay_program_id', inplace=True, verify_integrity=True)
    atsccgrounddelay_merged_df = pd.merge(atsccgrounddelay_df, atsccgrounddelayairports_tmp_df, how="left", left_index=True, right_index=True)
    atsccgrounddelayartccs_filename = "{0}{1}/{2}/atscc/flightstats_atsccgrounddelayartccs.csv".format(data_prefix, data_rev_prefix, date_prefix)
    atsccgrounddelayartccs_df = pd.read_csv(atsccgrounddelayartccs_filename, na_values=na_values)
    grouped = atsccgrounddelayartccs_df.groupby('ground_delay_program_id')
    groups = []
    i = 0
    for name, group in grouped:
        d = {}
    #   print "switching"
        d = {'ground_delay_program_id':int(name)}
        for k, row in enumerate(group.values):
    #        print row
            for j, val in enumerate(row):
                if group.columns[j] != "ground_delay_program_id":
                    d["{0}_{1}".format(k, group.columns[j])] = val
        groups.append(d)
        i += 1
    if len(groups) == 0:
        return None
    atsccgrounddelayartccs_tmp_df = pd.DataFrame(groups)
    atsccgrounddelayartccs_tmp_df.set_index('ground_delay_program_id', inplace=True, verify_integrity=True)
    #atsccgrounddelay_merged_df = pd.merge(atsccgrounddelay_merged_df, atsccgrounddelayartccs_tmp_df, how="left", left_index=True, right_index=True)
    end_time = []
    for ix,row in atsccgrounddelay_merged_df.iterrows():
        end = row['effective_end_time']
        if (end is None or end is np.nan) or (row['invalidated_time'] is not None and row['invalidated_time'] is not np.nan and row['invalidated_time'] < end):
            end = row['invalidated_time']
        if (end is None or end is np.nan) or (row['cancelled_time'] is not None and row['cancelled_time'] is not np.nan and row['cancelled_time'] < end):
            end = row['cancelled_time']
        end_time.append(end)
    atsccgrounddelay_merged_df['actual_end_time'] = pd.Series(end_time, index=atsccgrounddelay_merged_df.index)
    return atsccgrounddelay_merged_df

def merge(left, right):
    return pd.merge(left, right, how="left", left_on=['flight_history_id'], right_on=['flighthistoryid'])

def get_for_flights(df, data_prefix, data_rev_prefix, date_prefix, cutoff_time = None):
    atsccgrounddelay_merged_df = get_atscc_ground_delay(data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
    atsccdelay_df = get_atscc_delay(data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
    atsccdeicing_df = get_atscc_deicing(data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
    arrival_ground_delays = []
    arrival_ground_delays_df = None
    departure_ground_delays = []
    departure_ground_delays_df = None
    arrival_delays = []
    arrival_delays_df = None
    departure_delays = []
    departure_delays_df = None
    arrival_icing_delays = []
    arrival_icing_delays_df = None
    departure_icing_delays = []
    departure_icing_delays_df = None
    for ix, row in df.iterrows():
        arrival_grounddelay = {}
        departure_grounddelay = {}
        arrival_delay = {}
        departure_delay = {}
        arrival_icing_delay = {}
        departure_icing_delay = {}
        
        try:
            # if our scheduled gate arrival is within a ground delay
            if row['scheduled_gate_arrival'] is not None and row['scheduled_gate_arrival'] is not np.nan:
                
                if atsccgrounddelay_merged_df is not None:
                    tmp = atsccgrounddelay_merged_df[atsccgrounddelay_merged_df['airport_code'] == row['arrival_airport_code']]
                    tmp = tmp[tmp['effective_start_time'] <= row['scheduled_gate_arrival']]
                    tmp = tmp[tmp['actual_end_time'] >= row['scheduled_gate_arrival']]
                    tmp = tmp.sort_index(by='effective_start_time')
                    i = 0
                    for ix_tmp, row_tmp in tmp.iterrows():
                        for j, val in enumerate(row_tmp):
                            arrival_grounddelay["arrival_ground_delay_{0}_{1}".format(i, tmp.columns[j])] = val
                            #print row['scheduled_gate_arrival'], row['departure_airport_code'], row_tmp['effective_start_time'], row_tmp['effective_end_time'], row_tmp['airport_code']
                        i += 1
                    if len(arrival_grounddelay) > 0:
                        arrival_grounddelay['flight_history_id'] = ix
                        arrival_ground_delays.append(arrival_grounddelay)
                    
                tmp = atsccdelay_df[atsccdelay_df['airport_code'] == row['arrival_airport_code']]
                tmp = tmp[tmp['start_time'] <= row['scheduled_gate_arrival']]
                tmp = tmp[tmp['actual_end_time'] >= row['scheduled_gate_arrival']]
                tmp = tmp.sort_index(by='start_time')
                i = 0
                for ix_tmp, row_tmp in tmp.iterrows():
                    for j, val in enumerate(row_tmp):
                        arrival_delay["arrival_delay_{0}_{1}".format(i, tmp.columns[j])] = val
                    i += 1
                if len(arrival_delay) > 0:
                    arrival_delay['flight_history_id'] = ix
                    arrival_delays.append(arrival_delay)
                
                tmp = atsccdeicing_df[atsccdeicing_df['airport_code'] == row['arrival_airport_code']]
                tmp = tmp[tmp['start_time'] <= row['scheduled_gate_arrival']]
                tmp = tmp[tmp['actual_end_time'] >= row['scheduled_gate_arrival']]
                tmp = tmp.sort_index(by='start_time')
                i = 0
                for ix_tmp, row_tmp in tmp.iterrows():
                    for j, val in enumerate(row_tmp):
                        arrival_icing_delay["arrival_icing_delay_{0}_{1}".format(i, tmp.columns[j])] = val
                    i += 1
                if len(arrival_icing_delay) > 0:
                    arrival_icing_delay['flight_history_id'] = ix
                    arrival_icing_delays.append(arrival_icing_delay)
                    
            if row['scheduled_gate_departure'] is not None and row['scheduled_gate_departure'] is not np.nan:
                if atsccgrounddelay_merged_df is not None:
                    tmp = atsccgrounddelay_merged_df[atsccgrounddelay_merged_df['airport_code'] == row['departure_airport_code']]
                    tmp = tmp[tmp['effective_start_time'] <= row['scheduled_gate_departure']]
                    tmp = tmp[tmp['actual_end_time'] >= row['scheduled_gate_departure']]
                    tmp = tmp.sort_index(by='effective_start_time')
                    i = 0
                    for ix_tmp, row_tmp in tmp.iterrows():
                        for j, val in enumerate(row_tmp):
                            departure_grounddelay["departure_ground_delay_{0}_{1}".format(i, tmp.columns[j])] = val
                            #print row['scheduled_gate_arrival'], row['departure_airport_code'], row_tmp['effective_start_time'], row_tmp['effective_end_time'], row_tmp['airport_code']
                        i += 1
                    if len(departure_grounddelay) > 0:
                        departure_grounddelay['flight_history_id'] = ix
                        departure_ground_delays.append(departure_grounddelay)
                        #print departure_grounddelay
        
                tmp = atsccdelay_df[atsccdelay_df['airport_code'] == row['departure_airport_code']]
                tmp = tmp[tmp['start_time'] <= row['scheduled_gate_departure']]
                tmp = tmp[tmp['actual_end_time'] >= row['scheduled_gate_departure']]
                tmp = tmp.sort_index(by='start_time')
                i = 0
                for ix_tmp, row_tmp in tmp.iterrows():
                    for j, val in enumerate(row_tmp):
                        departure_delay["departure_delay_{0}_{1}".format(i, tmp.columns[j])] = val
                    i += 1
                if len(departure_delay) > 0:
                    departure_delay['flight_history_id'] = ix
                    departure_delays.append(departure_delay)
                
                tmp = atsccdeicing_df[atsccdeicing_df['airport_code'] == row['departure_airport_code']]
                tmp = tmp[tmp['start_time'] <= row['scheduled_gate_departure']]
                tmp = tmp[tmp['actual_end_time'] >= row['scheduled_gate_departure']]
                tmp = tmp.sort_index(by='start_time')
                i = 0
                for ix_tmp, row_tmp in tmp.iterrows():
                    for j, val in enumerate(row_tmp):
                        departure_icing_delay["departure_icing_delay_{0}_{1}".format(i, tmp.columns[j])] = val
                    i += 1
                if len(departure_icing_delay) > 0:
                    departure_icing_delay['flight_history_id'] = ix
                    departure_icing_delays.append(departure_icing_delay)
        except Exception as e:
            pass
    if len(arrival_ground_delays) > 0:
        arrival_ground_delays_df = pd.DataFrame(arrival_ground_delays)
        arrival_ground_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    if len(arrival_delays) > 0:
        arrival_delays_df = pd.DataFrame(arrival_delays)
        arrival_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    if len(arrival_icing_delays):
        arrival_icing_delays_df = pd.DataFrame(arrival_icing_delays)
        arrival_icing_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    if len(departure_ground_delays) > 0:
        departure_ground_delays_df = pd.DataFrame(departure_ground_delays)
        departure_ground_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    if len(departure_delays) > 0:
        departure_delays_df = pd.DataFrame(departure_delays)
        departure_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    if len(departure_icing_delays) > 0:
        departure_icing_delays_df = pd.DataFrame(departure_icing_delays)
        departure_icing_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    return (arrival_ground_delays_df, arrival_delays_df, arrival_icing_delays_df, departure_ground_delays_df, departure_delays_df, departure_icing_delays_df)


def get_joined_data(data_prefix, data_rev_prefix, date_prefix, store_filename, force=False, prefix="", cutoff_time = None, generate_features=None, unique_cols={}):
    try:
        store = pd.HDFStore(prefix+store_filename)
    except Exception as e:
        return None
    df = None
    print "{0}joined_{1}".format(prefix, date_prefix) in store, "force: {0}".format(force)
    if "{0}joined_{1}".format(prefix, date_prefix) in store and not force: 
        try:
            df = read_dataframe("{0}joined_{1}".format(prefix, date_prefix), store)
            if len(df.index) == 0:
                print "bad file {0}".format("{0}joined_{1}".format(prefix, date_prefix))
                df = None
            print "found {0}joined_{1} saved, returning".format(prefix, date_prefix)
        except Exception as e:
            print e
#            return None
    if df is None:
        print "Working on {0}".format(date_prefix)
        df = get_flight_history(data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
        events = get_flight_history_events(df, data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
        asdi_disposition = get_asdi_disposition(data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
        asdi_merged = get_asdi_merged(data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time) 
        joiners = [events, asdi_disposition, asdi_merged]
        df = df.join(joiners)
        print "joined events and asdi"
        per_flights = get_for_flights(df, data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
        for per_flight in per_flights:
            if per_flight is not None:
                df = df.join(per_flight)
        print "joined atscc"
    #        joiners = per_flights
    #        df = df.join(joiners)
        metar_arrival = get_metar("arrival", data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
        metar_departure = get_metar("departure", data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
        df = pd.merge(df, metar_arrival, how="left", left_on="arrival_airport_icao_code", right_index=True)
        df = pd.merge(df, metar_departure, how="left", left_on="departure_airport_icao_code", right_index=True)
        print "joined metar"
    #        fbwind_arrival = get_fbwind("arrival", data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
    #        fbwind_departure = get_fbwind("departure", data_prefix, data_rev_prefix, date_prefix,, cutoff_time=cutoff_time)
    #        df = pd.merge(df, fbwind_arrival, how="left", left_on="arrival_airport_code", right_index=True)
    #        df = pd.merge(df, fbwind_departure, how="left", left_on="departure_airport_code", right_index=True)
    #        taf_arrival = get_taf("arrival", data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
    #        df = pd.merge(df, taf_arrival, how="left", left_on="arrival_airport_code", right_index=True)
    #        taf_departure = get_taf("departure", data_prefix, data_rev_prefix, date_prefix, cutoff_time=cutoff_time)
    #        df = pd.merge(df, taf_departure, how="left", left_on="departure_airport_code", right_index=True)
        print "column type counts: {0}".format(df.get_dtype_counts())
        try:
            write_dataframe("{0}joined_{1}".format(prefix, date_prefix), df, store)
        except Exception as e:
            print e
            print traceback.format_exc()
    
    if generate_features:
        print "generating features"
        features_df = process_into_features(df, unique_cols, multi=False)
        features_df.to_csv("{0}features_{1}.csv".format(prefix, date_prefix))
    
    try:
        store.close()
    except Exception as e:
        print e
        print traceback.format_exc()
    return df

def get_joined_data_proxy(args):
    ''' Returns true or false if the join was successful '''
    data_prefix = args[0]
    data_rev_prefix = args[1]
    date_prefix = args[2]
    store_filename = args[3]
    prefix = ""
    if len(args) > 4:
        prefix = args[4]
    cutoff_time = None
    if len(args) > 5:
        cutoff_time = args[5]
    generate_features = False
    if len(args) > 6:
        generate_features = args[6]
    unique_cols = {}
    if len(args) > 7:
        unique_cols = args[7]
    print "date_prefix", date_prefix, "data_rev_prefix", data_rev_prefix, "date_prefix", date_prefix, "store_filename", store_filename, "prefix", prefix, "cutoff_time", cutoff_time, "generate_features", generate_features
    ret = False
    try:
        df = get_joined_data(data_prefix, data_rev_prefix, date_prefix, store_filename, prefix=prefix, cutoff_time=cutoff_time, generate_features=generate_features, unique_cols=unique_cols)
        if df is not None:
            ret = True
    except Exception as e:
        print e
        print traceback.format_exc()
    return ret

def handle_datetime(x, initial):
    pass

def minutes_difference(datetime1, datetime2):
    diff = datetime1 - datetime2
    return diff.days*24*60+diff.seconds/60

def process_column_into_features_proxy(args):
    unique_cols = args[0]
    column = args[1]
    series = args[2]
    scheduled_gate_arrival = args[3]
    scheduled_runway_arrival = args[4] 
    scheduled_runway_departure = args[5]
    return process_column_into_features(unique_cols, column, series, scheduled_gate_arrival, scheduled_runway_arrival, scheduled_runway_departure)

def process_column_into_features(unique_cols, column, series, scheduled_gate_arrival, scheduled_runway_arrival, scheduled_runway_departure):
    try:
        columns = {}
        columns_to_delete = []
        series = series.dropna()
        if len(series.values) == 0:
#            print "Column {0} is entirely nan's, deleting".format(column)
            return columns, columns_to_delete
        #create diff columns for estimates
        if "estimated_gate_arrival" in column:
            tmp = series - scheduled_gate_arrival
            columns["{0}_diff".format(column)] =  tmp.apply(lambda x:x.days * 24 * 60 + x.seconds / 60 if type(x) is datetime.timedelta else np.nan) 
        if 'estimated_runway_arrival' in column:
            tmp =  series - scheduled_runway_arrival
            columns["{0}_diff".format(column)] = tmp.apply(lambda x:x.days * 24 * 60 + x.seconds / 60 if type(x) is datetime.timedelta else np.nan)
        # I hate this, but I need to figure out the type and pandas has them as all objects
        dtype_tmp = get_column_type(series)
        if dtype_tmp is datetime.datetime:
#            print "datetime column: ", column
            columns['{0}_weekday'.format(column)] = series.apply(lambda x:x.weekday() if type(x) is datetime.datetime else np.nan)
            columns['{0}_day'.format(column)] = series.apply(lambda x:x.day if type(x) is datetime.datetime else np.nan)
            columns['{0}_hour'.format(column)] = series.apply(lambda x:x.hour if type(x) is datetime.datetime else np.nan)
            columns['{0}_minute'.format(column)] = series.apply(lambda x:x.minute if type(x) is datetime.datetime else np.nan) # get the diff relative to a zero-point
            columns['{0}_diff'.format(column)] = scheduled_runway_departure - series # set the diff to be in minutes
            columns['{0}_diff'.format(column)] = columns['{0}_diff'.format(column)].apply(lambda x:x.days * 24 * 60 + x.seconds / 60 if type(x) is datetime.timedelta else np.nan)
                # delete the original
            if column != "scheduled_runway_departure" and column != "scheduled_gate_arrival" and column != "scheduled_runway_arrival":
                columns_to_delete.append(column)
        elif dtype_tmp is str:
#            print column
            # this part is if we end up with a text column, break it up into bag of words
            #                for ix_b, val in series.iteritems():
            #                    if val is np.nan or str(val) == "nan" or type(val) is not str:
            #                        if type(val) is not str:
            #                            print "type was supposed to be str but was", val, ix_b, column
            #                        continue
            #                    words = val.split(" ")
            #                    words_dict = {}
            #                    if ix_b in bag_o_words:
            #                        words_dict = bag_o_words[ix_b]
            #                    words_dict['flight_history_id'.format()] = ix_b
            #                    nwords = 0
            #                    for word in words:
            #                        if len(word.strip()) > 0:
            #                            words_dict["{0}_{1}".format(column, word.strip())] = 1.0
            #                            nwords += 1
            #                    if nwords > 1:
            #                        bag_o_words[ix_b] = words_dict
            #                        if column not in bag_o_words_columns_to_delete:
            #                            bag_o_words_columns_to_delete.append(column)
            #                else:
            if column in unique_cols:
                columns[column] = series.apply(lambda x:unique_cols[column].index(x) if type(x) is str and x in unique_cols[column] and type(x) is not np.nan and str(x) != "nan" else np.nan)
            else:
                print "{0} was not in uniques".format(column)
        elif series.dtype is object or str(series.dtype) == "object":
            print "Column {0} is not a datetime and not a string, but is an object according to pandas".format(column) 
    except Exception as e:
        print "Error on column: {0}".format(column)
        print e
        import traceback
        print traceback.format_exc()
    return columns, columns_to_delete

def process_into_features(df, unique_cols, multi=True):
    df['gate_arrival_diff'] = df['actual_gate_arrival'] - df['scheduled_gate_arrival']
    df['gate_arrival_diff'] =  df['gate_arrival_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
    df['runway_arrival_diff'] = df['actual_runway_arrival'] - df['scheduled_runway_arrival']
    df['runway_arrival_diff'] =  df['runway_arrival_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
    df['gate_departure_diff'] = df['actual_gate_departure'] - df['scheduled_gate_departure']
    df['gate_departure_diff'] = df['gate_departure_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
    df['runway_departure_diff'] = df['actual_runway_departure'] - df['scheduled_runway_departure']
    df['runway_departure_diff'] = df['runway_departure_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
#    bag_o_words = {}
#    bag_o_words_columns_to_delete = []
    if multi:
        pool = Pool(processes=4)
        pool_queue = []
    results = []
    for i, (column, series) in enumerate(df.iteritems()):
        if "estimated_gate_arrival" in column or "estimated_runway_arrival" in column:
            # this fixes a mistake not setting something to np.nan when parsing
            df[column] = series.apply(lambda x: x if type(x) is datetime.datetime else np.nan)
            series = df[column]
        if multi:
            pool_queue.append([unique_cols, column, series, df['scheduled_gate_arrival'], df['scheduled_runway_arrival'], df['scheduled_runway_departure']])
        else:
            results.append(process_column_into_features(unique_cols, column, series, df['scheduled_gate_arrival'], df['scheduled_runway_arrival'], df['scheduled_runway_departure']))
#        columns, columns_to_delete = process_column_into_features()
    if multi:
        print "extracting features for {0} columns".format(len(pool_queue))
        results = pool.map(process_column_into_features_proxy, pool_queue, len(pool_queue)/8)
        pool.terminate()
    df_dict = df.to_dict("series")
    fac = int(len(results)/10)
    for i,result in enumerate(results):
        if i%fac == 0:
            print "Finalizing {0}/{1}".format(i, len(results))
        columns, columns_to_delete = result
        for column in columns.keys():
            df_dict[column] = columns[column]
        for column in columns_to_delete:
            del df_dict[column]
    df = pd.DataFrame(df_dict)
    print "recreated df after feature processing: ", df
    
    # join all the bag_o_words columns we found
#    bag_o_words_df = pd.DataFrame(bag_o_words.values())
#    bag_o_words_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
#    df = df.join(bag_o_words_df)
    # delete the original column that made the bag o words
#    for delete_column in bag_o_words_columns_to_delete:
#        del df[delete_column]
    if "scheduled_runway_departure" in df.columns:
        del df["scheduled_runway_departure"]
    if "scheduled_gate_arrival" in df.columns:
        del df["scheduled_gate_arrival"]
    if "scheduled_runway_arrival" in df.columns:
        del df["scheduled_runway_arrival"]
    df = df.convert_objects()
    for i, (column, series) in enumerate(df.iteritems()):
        if series.dtype is object or str(series.dtype) == "object":
            print "After convert types {0} is still an object, is nans {1}, deleting".format(column, len(series.dropna()) == 0)
            print series.dropna().values
            del df[column]
            #df[column] = df[column].astype(float)
    return df

def get_unique_values_for_categorical_columns_proxy(args):
    data_prefix = args[0]
    data_rev_prefix = args[1]
    subdirname = args[2]
    store_filename = args[3]
    df = get_joined_data(data_prefix, data_rev_prefix, subdirname, store_filename)
    unique_cols = {}
    return get_unique_values_for_categorical_columns(df, unique_cols)

def get_unique_values_for_categorical_columns(df, unique_cols):
    try:
        unique_columns = pickle.load(open("unique_columns.p",'rb'))
        return unique_columns
    except Exception as e:
        for i, (column, series) in enumerate(df.iteritems()):
            series = series.dropna()
            dtype_tmp = get_column_type(series)
            if series.dtype == "object" and dtype_tmp is str:
                us = np.unique(series, return_index=False, return_inverse=False)
#                grouped = df.groupby(column)
                if len(us) > 0:
                    if column not in unique_cols:
                            print "adding "+column, dtype_tmp, series.dtype
                            # add it to the unique cols map
                            unique_cols[column] = [] # if we have not seen this val before
                    for val in us:
                        if val not in unique_cols[column]: # append to the unqiue_cols for this column
                            unique_cols[column].append(val) # index is what we want to record for svm (svm uses floats not categorical data (strings))
            else:
                print "not uniquing {0} {1} {2}".format(column, dtype_tmp, series.dtype)
        return unique_cols

def get_predictions(cfr, features):
    max_prob = []
    predicted = cfr.predict(features)
    p = cfr.predict_proba(features)
    unique_classes = sorted(cfr.classes_[0])
    expectations = []
    for k, (ix, row) in enumerate(features.iterrows()):
        expectation = np.sum(unique_classes*p[k])
        expectations.append({'flight_history_id':ix, '{0}_expectation'.format(learned_class_name):expectation})
        max_prob.append({'flight_history_id':ix, '{0}_max_prob'.format(learned_class_name):predicted[k]})
        print "get_predictions", expectation, predicted[k]
    return expectations, max_prob

def get_metric(cfr, features, targets):
    sum_diff = 0.0
    p = cfr.predict_proba(features)
    unique_classes = sorted(cfr.classes_)
    for k, target in enumerate(targets):
        # expectation across all classes
        expectation = np.sum(unique_classes*p[k])
        sum_diff += np.sqrt(np.power((expectation - target),2))
    mean_diff = sum_diff/float(len(targets))
    return mean_diff

def random_forest_learn(targets, features):
    cfr = RandomForestClassifier(
        n_estimators=100,
        max_features=None,
        verbose=2,
        compute_importances=True,
        n_jobs=6,
        random_state=0,
        )
    cfr.fit(features, targets)
    return cfr

def random_forest_cross_validate(targets, features):
    cv = cross_validation.KFold(len(features), k=5, indices=False)
    #iterate through the training and test cross validation segments and
    #run the classifier on each one, aggregating the results into a list
    results = []
    for i, (traincv, testcv) in enumerate(cv):
        cfr = RandomForestClassifier(
        n_estimators=100,
        max_features=None,
        verbose=2,
        compute_importances=True,
        n_jobs=8,
        random_state=0,
        )
        print "Fitting cross validation #{0}".format(i)
        cfr.fit(features[traincv], targets[traincv])
        print "Scoring cross validation #{0}".format(i)
        score = cfr.score(features[testcv], targets[testcv])
        print "Score for cross validation #{0}, score: {1}".format(i, score)
#        print "Features importance"
#        features_list = []
#        for j, importance in enumerate(cfr.feature_importances_):
#            if importance > 0.0:
#                column = features.columns[j]
#                features_list.append((column, importance))
#        features_list = sorted(features_list, key=lambda x: x[1], reverse=True)
#        for j, tup in enumerate(features_list):
#            print j, tup
        unique_classes = sorted(cfr.classes_)
        mean_diff = get_metric(cfr, features, testcv, unique_classes)
        print "Mean difference: {0}".format(mean_diff)
        results.append(mean_diff)

    #print out the mean of the cross-validated results
    print "Results: " + str( np.array(results).mean() )

def concat(data_prefix, data_rev_prefix, subdirname, all_dfs, unique_cols, sample_size=None, exclude_df=None, include_df=None, prefix=""):
    print "Working on {0}".format(subdirname)
    store_filename = 'flight_quest_{0}.h5'.format(subdirname)
    try:
        df = get_joined_data(data_prefix, data_rev_prefix, subdirname, store_filename, prefix=prefix)
        # don't do this if we are predicting, this is a hack
        if "predict" not in prefix:
            df[learned_class_name] = df[actual_class] - df[scheduled_class]
            df[learned_class_name] =  df[learned_class_name].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
            # we have to have learned_class_name b/c it is the target so reduce set to
            # non-nan values
            df_tmp = df.ix[df[learned_class_name].dropna().index]
            if sample_size is not None:
                samples = sample_size
                rows = random.sample(df_tmp.index, samples)
                df_tmp = df_tmp.ix[rows]
            df = df_tmp
#        print "processing into features"
#        df = process_into_features(df, unique_cols)
#        print "features df after all processing: ", df
        before_count = len(df.index)
        if exclude_df is not None:
            keep_index = df.index - exclude_df.index
            df = df.ix[keep_index]
            print "Number before excluding features: {0} and after: {1}".format(before_count, len(df.index))
        before_count = len(df.index)
        if include_df is not None:
            df = df.ix[include_df.index & df.index]
            print "Number before including features: {0} and after: {1}".format(before_count, len(df.index))
    except Exception as e:
        print e
        return all_dfs
    if df is None:
        return all_dfs
    if all_dfs is None:
        all_dfs = df
    else:
        all_dfs = all_dfs.append(df)
        all_dfs.drop_duplicates(take_last=True, inplace=True)
        print all_dfs
    return all_dfs

def rebin_targets(targets, nbins):
    bin_max = np.max(targets)
    bin_min = np.min(targets)
    print "bin_max: {0}, bin_min: {1}".format(bin_max, bin_min)
    bins = np.linspace(bin_min, bin_max, nbins) 
    digitized = np.digitize(orig_bins, bins)
    new_bins = []
    for digit in digitized:
        if digit == len(bins):
            new_bins.append(bins[digit-1])
        else:
            new_bins.append((bins[digit-1] + bins[digit])/2.0)
    return new_bins

def add_previous_flights_features(learned_class_name, data_prefix, data_rev_prefix, augmented_data_rev_prefix):
    all_df = pd.read_csv("features_{0}.csv".format(learned_class_name))
    all_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    store = pd.HDFStore('flight_quest.h5')
    all_flight_histories = None
    if 'flight_histories' not in store:
        for subdirname in os.walk('{0}{1}'.format(data_prefix, data_rev_prefix)).next()[1]:
            df = get_flight_history(data_prefix, data_rev_prefix, subdirname)
            if all_flight_histories is None:
                all_flight_histories = df
            else:
                all_flight_histories.append(df)
                all_flight_histories.drop_duplicates(take_last=True, inplace=True)
        for subdirname in os.walk('{0}{1}'.format(data_prefix, augmented_data_rev_prefix)).next()[1]:
            df = get_flight_history(data_prefix, augmented_data_rev_prefix, subdirname)
            if all_flight_histories is None:
                all_flight_histories = df
            else:
                all_flight_histories.append(df)
                all_flight_histories.drop_duplicates(take_last=True, inplace=True)
        store['flight_histories'] = all_flight_histories
    else:
        all_flight_histories = store['flight_histories']
    all_df['actual_runway_departure'] = all_flight_histories['actual_runway_departure']
    new_cols = []
    for ix, row in all_df.iterrows():
        if row['actual_runway_departure'] is np.nan:
            continue
        df_tmp = all_df[all_df['actual_runway_departure'] < row['actual_runway_departure']]
        df_tmp = df_tmp[df_tmp['arrival_airport_code'] == row['arrival_airport_code']]
        # careful of sotring ascending false
        df_tmp = df_tmp.sort_index(by='actual_runway_departure', ascending=False)
        # setup a dictionary for this ix/row
        tmp_dict = {'flight_history_id':ix}
        # loop through the last 10 flights to the same arrival airport < than the current
        for i, (ix_tmp, row_tmp) in enumerate(df_tmp.iterrows()[0:10]):
            if row_tmp['actual_runway_departure'] is np.nan:
                continue
            # loop through the colmns
            for column, val in row_tmp:
                # add the columns we want to the dict 
                if 'last_estimated_gate_arrival' in column or 'last_estimated_runway_arrival' in column or 'runway_departure_diff' in column or 'gate_departure_diff':
                    tmp_dict["{0}_{1}".format(i, column)] = val
            tmp_dict["{0}_{1}".format(i, 'runway_departure_diff')] = row['actual_runway_departure'] - row_tmp['actual_runway_departure']
        # append the dict for this ix/row
        new_cols.append(dict)
    new_cols_df = pd.DataFrame(new_cols)
    new_cols_df.set_index('flight_history_id',inplace=True, verify_integrity=True)
    all_df = all_df.join(new_cols_df)
    del all_df['actual_runway_departure']
    all_df.to_csv("features_plus_previous_flights_{0}".format(learned_class_name)) 
        
    

def build_uniques(store_filename, data_prefix, data_rev_prefix, augmented_data_rev_prefix):
    pool_queue = []
    pool = Pool(processes=4)
    for subdirname in os.walk('{0}{1}'.format(data_prefix, data_rev_prefix)).next()[1]:
        print "Working on {0}".format(subdirname)
        store_filename = 'flight_quest_{0}.h5'.format(subdirname)
        pool_queue.append([data_prefix, data_rev_prefix, subdirname, store_filename]) #            unique_cols = get_unique_values_for_categorical_columns(df, unique_cols)
    
    for subdirname in os.walk('{0}{1}'.format(data_prefix, augmented_data_rev_prefix)).next()[1]:
        print "Working on {0}".format(subdirname)
        store_filename = 'flight_quest_{0}.h5'.format(subdirname)
        pool_queue.append([data_prefix, augmented_data_rev_prefix, subdirname, store_filename]) #            unique_cols = get_unique_values_for_categorical_columns(df, unique_cols)
    
    results = pool.map(get_unique_values_for_categorical_columns_proxy, pool_queue, 1)
    pickle.dump(results, open("uniques_backup.p", 'wb'))
    pool.terminate()
    all_unique_cols = {}
    for unique_cols in results:
    # dict of column : list of values
        for col in unique_cols.keys():
            unique_values = unique_cols[col]
            if col not in all_unique_cols:
                all_unique_cols[col] = []
            if len(unique_values) > 0: # concat
                all_unique_cols[col] = all_unique_cols[col] + unique_values
    
    pickle.dump(all_unique_cols, open("unique_columns.p", "wb"))

def build_multi(store_filename, data_prefix, data_rev_prefix, augmented_data_rev_prefix):
    pool_queue = []
    pool = Pool(processes=4)
    for subdirname in os.walk('{0}{1}'.format(data_prefix, data_rev_prefix)).next()[1]:
        store_filename = 'flight_quest_{0}.h5'.format(subdirname)
        pool_queue.append([data_prefix, data_rev_prefix, subdirname, store_filename])
    
    for subdirname in os.walk('{0}{1}'.format(data_prefix, augmented_data_rev_prefix)).next()[1]:
        store_filename = 'flight_quest_{0}.h5'.format(subdirname)
        pool_queue.append([data_prefix, augmented_data_rev_prefix, subdirname, store_filename])
    
    results = pool.map(get_joined_data_proxy, pool_queue, 1)
    pool.terminate()
    
def build_test(data_prefix, test_data_training_rev_prefix, test_data_rev_prefix):
    include_df = pd.read_csv('{0}{1}/test_flights_combined.csv'.format(data_prefix, test_data_rev_prefix), index_col=0, parse_dates=[5, 6, 7, 8], date_parser=parse_date_time)
    data = {}
    for subdirname in os.walk('{0}{1}'.format(data_prefix, test_data_training_rev_prefix)).next()[1]:
        print "Working on {0}".format(subdirname)
        subdir_date = datetime.datetime.strptime(subdirname, "%Y_%m_%d")
        midnight_time = datetime.datetime(subdir_date.year, subdir_date.month, subdir_date.day, tzinfo=tz.tzutc())
        df = get_flight_history(data_prefix, test_data_training_rev_prefix, subdirname)
        df = df.ix[include_df.index]
        for ix, row in df.iterrows():
            if ix not in data:
                data[ix] = {'flight_history_id':ix, "midnight_time":midnight_time, "scheduled_runway_arrival":include_df.ix[ix]['scheduled_runway_arrival'], "scheduled_gate_arrival":include_df.ix[ix]['scheduled_gate_arrival'], "actual_runway_arrival":np.nan, "actual_gate_arrival":np.nan}
                if row['actual_runway_arrival'] is not np.nan:
                    data[ix]["actual_runway_arrival"] = minutes_difference(row['actual_runway_arrival'], midnight_time)
                if row['actual_gate_arrival'] is not np.nan:
                    data[ix]["actual_gate_arrival"] = minutes_difference(row['actual_gate_arrival'], midnight_time)
            else:
                tmp = data[ix]
                if tmp["actual_runway_arrival"] is np.nan:
                    if row['actual_runway_arrival'] is not np.nan:
                        tmp["actual_runway_arrival"] = minutes_difference(row['actual_runway_arrival'], midnight_time)
                if tmp["actual_gate_arrival"] is np.nan:
                    if row["actual_gate_arrival"] is not np.nan:
                        tmp["actual_gate_arrival"] = minutes_difference(row['actual_gate_arrival'], midnight_time)
    new_df = pd.DataFrame(data.values())
    new_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    new_df.to_csv("test_flights_combined.csv")


def build_multi_features(store_filename, data_prefix, data_rev_prefix, augmented_data_rev_prefix):
    unique_columns = pickle.load(open("unique_columns.p", 'rb'))
    pool_queue = []
    pool = Pool(processes=2)
    for subdirname in os.walk('{0}{1}'.format(data_prefix, data_rev_prefix)).next()[1]:
        if not os.path.exists("{0}features_{1}.csv".format("", subdirname)):
            store_filename = 'flight_quest_{0}.h5'.format(subdirname)
            pool_queue.append([data_prefix, data_rev_prefix, subdirname, store_filename, "", None, True, unique_columns])
    
    for subdirname in os.walk('{0}{1}'.format(data_prefix, augmented_data_rev_prefix)).next()[1]:
        if not os.path.exists("{0}features_{1}.csv".format("", subdirname)):
            store_filename = 'flight_quest_{0}.h5'.format(subdirname)
            pool_queue.append([data_prefix, augmented_data_rev_prefix, subdirname, store_filename, "", None, True, unique_columns])
    
    results = pool.map(get_joined_data_proxy, pool_queue, 1)
    pool.terminate()

def build_predict(store_filename, data_prefix, test_data_rev_prefix):
    pool_queue = []
    pool = Pool(processes=4)
    for subdirname in os.walk('{0}{1}'.format(data_prefix, test_data_rev_prefix)).next()[1]:
        store_filename = 'flight_quest_{0}.h5'.format(subdirname)
        pool_queue.append([data_prefix, test_data_rev_prefix, subdirname, store_filename, "predict_"])
    
    results = pool.map(get_joined_data_proxy, pool_queue, 1)
    pool.terminate()

def concat_data(learned_class_name, store, data_prefix, data_rev_prefix, augmented_data_rev_prefix, sample_size):
    all_dfs = None
    unique_columns = pickle.load(open("unique_columns.p", 'rb'))
    for subdirname in os.walk('{0}{1}'.format(data_prefix, data_rev_prefix)).next()[1]:
        all_dfs = concat(data_prefix, data_rev_prefix, subdirname, all_dfs, unique_columns, sample_size=sample_size)
    
    for subdirname in os.walk('{0}{1}'.format(data_prefix, augmented_data_rev_prefix)).next()[1]:
        all_dfs = concat(data_prefix, augmented_data_rev_prefix, subdirname, all_dfs, unique_columns, sample_size=sample_size)
    
    all_dfs.to_csv("all_joined_{0}.csv".format(learned_class_name))
    store = pd.HDFStore('all_joined_{0}.h5'.format(learned_class_name))
    write_dataframe("all_joined_{0}".format(learned_class_name), all_dfs, store)

def concat_features(learned_class_name, data_prefix, data_rev_prefix, augmented_data_rev_prefix, sample_size):
    all_dfs = None
    for subdirname in os.walk('{0}{1}'.format(data_prefix, data_rev_prefix)).next()[1]:
        print "Working on {0}".format(subdirname)
        df_tmp = pd.read_csv("{0}features_{1}.csv".format("", subdirname))
        if sample_size is not None:
            samples = sample_size
            rows = random.sample(df_tmp.index, samples)
            df_tmp = df_tmp.ix[rows]
        if all_dfs is None:
            all_dfs = df_tmp
        else:
            all_dfs = all_dfs.append(df_tmp)
        print "new length {0}".format(all_dfs)
    
    for subdirname in os.walk('{0}{1}'.format(data_prefix, augmented_data_rev_prefix)).next()[1]:
        print "Working on {0}".format(subdirname)
        df_tmp = pd.read_csv("{0}features_{1}.csv".format("", subdirname))
        if sample_size is not None:
            samples = sample_size
            rows = random.sample(df_tmp.index, samples)
            df_tmp = df_tmp.ix[rows]
        if all_dfs is None:
            all_dfs = pd.read_csv(df_tmp)
        else:
            all_dfs = all_dfs.append(df_tmp)
        print "new length {0}".format(all_dfs)
    
    all_dfs.to_csv("features_{0}.csv".format(learned_class_name), index_label="ind")

def concat_predict(learned_class_name, store, data_prefix, test_data_rev_prefix, all_dfs):
    unique_columns = pickle.load(open("unique_columns.p", 'rb'))
    for subdirname in os.walk('{0}{1}'.format(data_prefix, test_data_rev_prefix)).next()[1]:
        include_df = pd.read_csv('{0}{1}/test_flights_combined.csv'.format(data_prefix, test_data_rev_prefix), index_col=0)
        all_dfs = concat(data_prefix, test_data_rev_prefix, subdirname, all_dfs, unique_columns, include_df=include_df, prefix="predict_")
    
    all_dfs.to_csv("predict_all_joined_{0}.csv".format(learned_class_name))
    store = pd.HDFStore('predict_all_joined_{0}.h5'.format(learned_class_name))
    write_dataframe("predict_all_joined_{0}".format(learned_class_name), all_dfs, store)

def generate_features(learned_class_name, store):
    unique_cols = {}
    all_df = read_dataframe("all_joined_{0}".format(learned_class_name), store)
    unique_cols = get_unique_values_for_categorical_columns(all_df, unique_cols)
    all_df = process_into_features(all_df, unique_cols)
    all_df.to_csv("features_{0}.csv".format(learned_class_name))
    store = pd.HDFStore('features_{0}.h5'.format(learned_class_name))
    write_dataframe("features_{0}".format(learned_class_name), all_df, store)

def cross_validate(learned_class_name):
    all_df = pd.read_csv("features_{0}.csv".format(learned_class_name), nrows=1) 
    all_df.set_index("flight_history_id", inplace=True, verify_integrity=True)
    del all_df[learned_class_name]
    # fix screw up with index column
    if "ind" in all_df.columns:
        del all_df["ind"]
    print learned_class_name
    print all_df
    series = all_df[learned_class_name]
    series = series.dropna()
    all_df = all_df.ix[series.index]
    print len(all_df)
    targets = series.dropna()
    print len(targets.index)
    targets = targets.apply(lambda x:myround(x, base=1))
    features = all_df
    del features[learned_class_name]
    random_forest_cross_validate(targets, features)
    
def test(learned_class_name, store):
    print "reading testing truth data from store" # assumes model already learned
    # load the test truth data
    test_df = pd.read_csv("test_flights_combined.csv", index_col=0, parse_dates=[3,4,5], date_parser=parse_date_time) # we need the features we trained from, in order to normalize the columns
    # load the first row of the training features, so we get the columns
    print "reading training columns"
    all_df = pd.read_csv("features_{0}.csv".format(learned_class_name), nrows=1) 
    all_df.set_index("flight_history_id", inplace=True, verify_integrity=True)
    del all_df[learned_class_name]
    # fix screw up with index column
    if "ind" in all_df.columns:
        del all_df["ind"]
    # load the model
    print "reading testing features from store "
    test_features_df = pd.read_csv("predict_features_{0}.csv".format(learned_class_name), nrows=10)
    test_features_df.set_index("flight_history_id", inplace=True, verify_integrity=True)
    # This should normalize the features used for learning columns with the features used for predicting
    for column in all_df.columns:
        if column not in test_features_df.columns:
            test_features_df[column] = pd.Series(index=test_features_df.index)
    
    for column in test_features_df.columns:
        if column not in all_df.columns:
            del test_features_df[column] # choose the column we are working on
    for column in test_features_df.columns:
        if column not in all_df.columns:
            print column
    print len(test_features_df.columns)
    # ensure columns are in same order as training
    test_features_df = test_features_df.reindex(columns=all_df.columns) 
    for i, col in enumerate(test_features_df.columns):
        if col != all_df.columns[i]:
            print "columns don't match after reindex", col
    # map the learned_class_name to the test_class for comparison
    arrival_column = "actual_gate_arrival"
    if learned_class_name == "diff_runway_arrival":
        arrival_column = "actual_runway_arrival"
    # features we want to test are the ones in the test file
    features = test_features_df.ix[test_df.index]
    # predict
    print "reading model"
    cfr = pickle.load(open("cfr_model_{0}.p".format(learned_class_name), 'rb')) 
    cfr.set_params(n_jobs=1) # read in the features to predict, remove bad columns
    print "predicting"
    expectations, max_likes = get_predictions(cfr, features) # loop through test_df and compute the difference b/t actual and expected
    print "computing stats"
    summer = 0.0
    for i, (ix, row) in enumerate(test_features_df.iterrows()):
        midnight_time = test_df.ix[ix]['midnight_time']
        predicted_arrival = minutes_difference(test_df.ix[ix]['scheduled_gate_arrival'], midnight_time) + expectations[i]
        actual_arrival = test_df.ix[ix][arrival_column]
        print predicted_arrival, actual_arrival
        summer += np.sqrt(np.power((actual_arrival - predicted_arrival), 2))
    
    print "MSE for {0}: {1}".format(arrival_column, summer / float(len(expectations)))

def reduce_features(learned_class_name):
    all_df = pd.read_csv("features_{0}.csv".format(learned_class_name))
    all_df.set_index("flight_history_id", inplace=True, verify_integrity=True)
    number_columns = {}
    for column, series in all_df.iteritems():
        splits = column.split("_")
        if splits[0].isdigit():
            tmp = "_".join(splits[1:])
            if tmp not in number_columns:
                number_columns[tmp] = [int(splits[0])]
            else:
                number_columns[tmp].append(int(splits[0]))
    cols_to_delete = []
    for key in number_columns.keys():
        tmp = sorted(number_columns[key], reverse=True)
        # keep the top 100
        for val in tmp[100:]:
            print "{0}_{1}".format(val, key)
            cols_to_delete.append("{0}_{1}".format(val, key))
    for col in cols_to_delete:
        del all_df[col]
    all_df.to_csv("reduced_features_{0}.csv".format(learned_class_name))

def useful_features(leanred_class_name):
    print "Features importance"
    features = pd.read_csv("features_{0}.csv".format(learned_class_name), nrows=1)
    del features[learned_class_name]
    cfr = pickle.load(open("cfr_model_{0}.p".format(learned_class_name), 'rb'))
    features_list = []
    for j, importance in enumerate(cfr.feature_importances_):
        if importance > 0.0:
            column = features.columns[j]
            features_list.append((column, importance))
    features_list = sorted(features_list, key=lambda x: x[1], reverse=True)
    for j, tup in enumerate(features_list):
        print j, tup

def learn(learned_class_name):
    all_df = pd.read_csv("features_{0}.csv".format(learned_class_name), nrows=5000)
    all_df.set_index("flight_history_id", inplace=True, verify_integrity=True)
    #fix screwup
    if "ind" in all_df.columns:
        print "deleting ind"
        del all_df["ind"]
    for i, (column, series) in enumerate(all_df.iteritems()):
        if series.dtype is object or str(series.dtype) == "object":
            print "AFter convert types {0} is still an object".format(column)
            if len(series.dropna()) > 0:
                print "is all nan and not 0:  {0}".format(len(series.dropna()))
            del all_df[column]
    print learned_class_name
    print all_df
    series = all_df[learned_class_name]
    series = series.dropna()
    all_df = all_df.ix[series.index]
    print len(all_df)
    targets = series.dropna()
    print len(targets.index)
    targets = targets.apply(lambda x:myround(x, base=1))
    features = all_df
    del features[learned_class_name]
    print len(targets.index), len(features.index), len(features.columns) # remove the target from the features
    cfr = random_forest_learn(targets, features)
    pickle.dump(cfr, open("cfr_model_{0}.p".format(learned_class_name), 'wb'))

def generate_features_predict(learned_class_name, store):
    unique_cols = {}
    store = pd.HDFStore('predict_all_joined_{0}.h5'.format(learned_class_name))
    all_df = read_dataframe("predict_all_joined_{0}".format(learned_class_name), store)
    unique_cols = get_unique_values_for_categorical_columns(all_df, unique_cols)
    all_df = process_into_features(all_df, unique_cols)
    all_df.to_csv("predict_features_{0}.csv".format(learned_class_name))
    store = pd.HDFStore('predict_features_{0}.h5'.format(learned_class_name))
    write_dataframe("predict_features_{0}".format(learned_class_name), all_df, store)

def predict(learned_class_name, features_to_remove, store):
    print "reading features from store"
    cfr = pickle.load(open("cfr_model_{0}.p".format(learned_class_name), 'rb'))
    print cfr.classes_[0] # n_jobs breaks this from the pickle
    cfr.set_params(n_jobs=1) # read in the features to predict, remove bad columns
    test_all_df = pd.read_csv("predict_features_{0}.csv".format(learned_class_name), index_col=0)
    for i, (column, series) in enumerate(test_all_df.iteritems()):
        if series.dtype is object or str(series.dtype) == "object":
            print "AFter convert types {0} is still an object".format(column)
            if len(series.dropna()) > 0:
                print "is all nan and not 0:  {0}".format(len(series.dropna()))
            del test_all_df[column] # read in the training features remove bad columns
    
    all_df = pd.read_csv("features_{0}.csv".format(learned_class_name), nrows=1)
    all_df.set_index("flight_history_id", inplace=True, verify_integrity=True)
    if "ind" in all_df.columns:
        del all_df["ind"]
    
# This should normalize the features used for learning columns with the features used for predicting
    for column in all_df.columns:
        if column not in test_all_df.columns:
            test_all_df[column] = pd.Series(index=test_all_df.index)
    
    for column in test_all_df.columns:
        if column not in all_df.columns:
            del test_all_df[column] # re-index with the columns from the learned features to establish proper ordering
    
    test_all_df = test_all_df.reindex(columns=all_df.columns)
            # remove all the columns that we might have, this is an expirement, not sure I need to remove anything
            # but the one I am targeting
#    for col in features_to_remove:
#        if col in test_all_df.columns:
#            del test_all_df[col]
    
    expectations, max_probs = get_predictions(cfr, test_all_df) # create expectations df and output
    expect_df = pd.DataFrame(expectations)
    expect_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    expect_df.to_csv('expecations_{0}.csv'.format(learned_class_name)) # create max_probability df and output
    max_prob_df = pd.DataFrame(max_probs)
    max_prob_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    max_prob_df.to_csv('max_prob_{0}.csv'.format(learned_class_name))

def finalize(store_filename, data_prefix, data_rev_prefix, test_data_rev_prefix):
    # load in the predictions
    gate_arrival_expectations = pd.read_csv('expectations_{0}.csv'.format("gate_arrival_diff"), index_col=0)
    runway_arrival_expectations = pd.read_csv('expectations_{0}.csv'.format("runway_arrival_diff"), index_col=0)
    print "len(gate_arrival_expectations):{0} should equal len(runway_arrival_expectations) {1}".format(len(gate_arrival_expectations.index), len(runway_arrival_expectations.index)) # join them together
    all_expectations = gate_arrival_expectations.join(runway_arrival_expectations) # create new coumns for the values we want
    all_expectations['actual_gate_arrival'] = np.nan
    all_expectations['actual_runway_arrival'] = np.nan
    all_expectations['midnight_time'] = np.nan
    # find out what day the fligh_history_ids are from, so we know midnight
    for subdirname in os.walk('{0}{1}'.format(data_prefix, test_data_rev_prefix)).next()[1]:
        store_filename = 'flight_quest_{0}.h5'.format(subdirname)
        subdir_date = datetime.datetime.strptime(subdirname, "%Y_%m_%d")
        midnight_time = datetime.datetime(subdir_date.year, subdir_date.month, subdir_date.day, tzinfo=tz.tzutc())
        df = get_joined_data(data_prefix, data_rev_prefix, subdirname, store_filename) # get the intersection of the ids in our expectations and the current df
        intersection = all_expectations & df
    # loop through teh intersection and compute minutes after midnight, store it in the columns we created
        for ix, row in all_expectations.ix[intersection]: #df[learned_class_name] = df[actual_class] - df[scheduled_class]
            # so df[actual_class] = df[learned_class_name] + df[scheduled_class]
            row['actual_gate_arrival'] = minutes_difference(df.ix[ix]['scheduled_gate_arrival'], midnight_time) + row['gate_arrival_diff_expectation']
            row['actual_runway_arrival'] = minutes_difference(df.ix[ix]['scheduled_runway_arrival'], midnight_time) + row['runway_arrival_diff_expectation']
            row['midnight_time'] = midnight_time # output the final format
    
    all_expectations.to_csv("expectations_solution_combined.csv", cols=['actual_gate_arrival', 'actual_runway_arrival', 'midnight_time', 'scheduled_gate_arrival', 'scheduled_runway_arrival'], index_label="flight_history_id")


if __name__ == '__main__':
    store = pd.HDFStore('flight_quest.h5')
    store_filename = 'flight_quest.h5'
    data_prefix = '/Users/jostheim/workspace/kaggle/data/flight_quest/'
    data_rev_prefix = 'InitialTrainingSet_rev1'
    augmented_data_rev_prefix = 'AugmentedTrainingSet1'
    augmented2_data_rev_prefix = 'AugmentedTrainingSet2'
    test_data_training_rev_prefix = 'PublicLeaderboardTrainDays'
    test_data_rev_prefix = 'PublicLeaderboardSet'
    kind = sys.argv[1]
    if len(sys.argv) > 2:
        learned_class_name = sys.argv[2]
    if len(sys.argv) > 3:
        scheduled_class = sys.argv[3]
    if len(sys.argv) > 4:
        actual_class = sys.argv[4]
    sample_size = None
    if len(sys.argv) > 5:
        sample_size = int(sys.argv[5])
    if kind == "build_multi":
        build_multi(store_filename, data_prefix, data_rev_prefix, augmented_data_rev_prefix)
    elif kind == "build_test":
        build_test(data_prefix, test_data_training_rev_prefix, test_data_rev_prefix)
    elif kind == "build_multi_features":
        build_multi_features(store_filename, data_prefix, data_rev_prefix, augmented_data_rev_prefix)
    elif kind == "build_predict":
        build_predict(store_filename, data_prefix, test_data_rev_prefix)
    elif kind == "concat":
        concat_data(learned_class_name, store, data_prefix, data_rev_prefix, augmented_data_rev_prefix, sample_size)
    elif kind == "concat_features":
        concat_features(learned_class_name, data_prefix, data_rev_prefix, augmented_data_rev_prefix, sample_size)
    elif kind == "concat_predict":
        all_dfs = None
        concat_predict(learned_class_name, store, data_prefix, test_data_rev_prefix, all_dfs)
    elif kind == "generate_features":
        generate_features(learned_class_name, store)
    elif kind == "generate_features_predict":
        generate_features_predict(learned_class_name, store)
    elif kind == "uniques":
        ''' Get dict of dict of lists for columns to unique categorical values in the columns '''
        build_uniques(store_filename, data_prefix, data_rev_prefix, augmented_data_rev_prefix)
    elif kind == "cross_validate":
        cross_validate(learned_class_name)
    elif kind == "test":
        test(learned_class_name, store)
    elif kind == "learn":
        print "reading features from store"
        learn(learned_class_name)
    elif kind == "predict":
        predict(learned_class_name, features_to_remove, store)
    elif kind == "finalize_output":
        finalize(store_filename, data_prefix, data_rev_prefix, test_data_rev_prefix)
    elif kind == "reduce_features":
        reduce_features(learned_class_name)
    elif kind == "useful_features":
        useful_features(learned_class_name)















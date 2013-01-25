'''
Created on Jan 6, 2013

@author: jostheim
'''
import pandas as pd
import numpy as np
import types
import dateutil
import datetime
from multiprocessing import Pool
import os, sys
import random
import pickle
from pytz import timezone
from flight_history_events import get_estimated_gate_arrival_string, get_estimated_runway_arrival_string
from sklearn.ensemble import RandomForestClassifier
from sklearn import cross_validation

data_prefix = '/Users/jostheim/workspace/kaggle/data/flight_quest/'
data_rev_prefix = 'InitialTrainingSet_rev1'
date_prefix = '2012_11_12'
data_test_rev_prefix = 'SampleTestSet'
na_values = ["MISSING", "HIDDEN"]
do_not_convert_to_date = ["icao_aircraft_type_actual"]
store = pd.HDFStore('flight_quest.h5')

def myround(x, base=5):
    return int(base * round(float(x)/base))

def parse_date_time(val):
    if str(val).lower().strip() not in na_values and str(val).lower().strip() != "nan":
        #'2012-11-12 17:30:00+00:00
        try:
            return dateutil.parser.parse(val)
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

def write_dataframe(name, df):
#    types = []
#    for column in df.columns:
#        types.append(get_column_type(df[column]))
#    pickle.dump(types, open("{0}.header".format(name), 'wb'))
#    df.to_csv("{0}.csv".format(name))
    store[name] = df

def read_dataframe(name, convert_dates_switch = True):
#    types = pickle.load(open("{0}.header".format(name), 'rb'))
#    dates = []
#    for i, typee in enumerate(types):
#        if typee is datetime.datetime:
#            dates.append(i+1)
#    df = pd.read_csv("{0}.csv".format(name), index_col=0)
#    if convert_dates_switch:
#        print "converting dates"
#        for column, series  in df.iteritems():
#            if column not in do_not_convert_to_date:
#                df[column] = series.apply(lambda x: convert_dates(x) if type(x) is str else x) 
#    print "dropping duplicates"
#    df.drop_duplicates(take_last=True, inplace=True)
    return store[name]

def get_column_type(series):
    dtype_tmp = None
    for ix, type_val in series.dropna().iteritems():
        if type_val is not np.nan and str(type_val) != "nan":
            dtype_tmp = type(type_val)
            return dtype_tmp
        
def get_flight_history():
    filename = "{0}/{1}/{2}/FlightHistory/flighthistory.csv".format(data_prefix, data_rev_prefix, date_prefix)
    df = pd.read_csv(filename, index_col=0, parse_dates=[7,8,9,10,11,12,13,14,15,16,17], date_parser=parse_date_time, na_values=na_values)
    return df

def get_metar(prefix):
    filename = "{0}/{1}/{2}/metar/flightstats_metarreports_combined.csv".format(data_prefix, data_rev_prefix, date_prefix)
    metar_df = pd.read_csv(filename, index_col=['metar_reports_id'], parse_dates=[2], date_parser=parse_date_time, na_values=na_values)
    filename = "{0}/{1}/{2}/metar/flightstats_metarpresentconditions_combined.csv".format(data_prefix, data_rev_prefix, date_prefix)
    metar_present_conditions_df = pd.read_csv(filename, index_col=['metar_reports_id'], na_values=na_values)
    del metar_present_conditions_df['id'] 
    filename = "{0}/{1}/{2}/metar/flightstats_metarrunwaygroups_combined.csv".format(data_prefix, data_rev_prefix, date_prefix)
    metar_runway_groups_df = pd.read_csv(filename, index_col=['metar_reports_id'], na_values=na_values)
    del metar_runway_groups_df['id'] 
    filename = "{0}/{1}/{2}/metar/flightstats_metarskyconditions_combined.csv".format(data_prefix, data_rev_prefix, date_prefix)
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

def get_taf(prefix):
    filename = "/Users/jostheim/workspace/kaggle/data/flight_quest/InitialTrainingSet_rev1/2012_11_12/otherweather/flightstats_taf.csv"
    taf_df = pd.read_csv(filename, index_col=['tafid'], parse_dates=[8,9,10,11], date_parser=parse_date_time, na_values=["MISSING"])
    filename = "/Users/jostheim/workspace/kaggle/data/flight_quest/InitialTrainingSet_rev1/2012_11_12/otherweather/flightstats_tafforecast.csv"
    taf_forceast_df = pd.read_csv(filename, index_col=['tafforecastid'], parse_dates=[4,5,7], date_parser=parse_date_time, na_values=["MISSING"])
    filename = "/Users/jostheim/workspace/kaggle/data/flight_quest/InitialTrainingSet_rev1/2012_11_12/otherweather/flightstats_taficing.csv"
    taf_icing_df = pd.read_csv(filename, na_values=["MISSING"])
    filename = "/Users/jostheim/workspace/kaggle/data/flight_quest/InitialTrainingSet_rev1/2012_11_12/otherweather/flightstats_tafsky.csv"
    taf_sky_df = pd.read_csv(filename, na_values=["MISSING"])
    filename = "/Users/jostheim/workspace/kaggle/data/flight_quest/InitialTrainingSet_rev1/2012_11_12/otherweather/flightstats_taftemperature.csv"
    taf_temperature_df = pd.read_csv(filename, na_values=["MISSING"])
    filename = "/Users/jostheim/workspace/kaggle/data/flight_quest/InitialTrainingSet_rev1/2012_11_12/otherweather/flightstats_tafturbulence.csv"
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

def get_fbwind(prefix):
    filename = "{0}/{1}/{2}/otherweather/flightstats_fbwindreport.csv".format(data_prefix, data_rev_prefix, date_prefix)
    fbwindreport_df = pd.read_csv(filename, parse_dates=[1], date_parser=parse_date_time, na_values=na_values)
    filename = "{0}/{1}/{2}/otherweather/flightstats_fbwindairport.csv".format(data_prefix, data_rev_prefix, date_prefix)
    fbwindairport_df = pd.read_csv(filename, na_values=na_values)
    filename = "{0}/{1}/{2}/otherweather/flightstats_fbwind.csv".format(data_prefix, data_rev_prefix, date_prefix)
    fbwind_df = pd.read_csv(filename, na_values=na_values)
    filename = "{0}/{1}/{2}/otherweather/flightstats_fbwindaltitude.csv".format(data_prefix, data_rev_prefix, date_prefix)
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
    print fbwind_joined.values
    
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

def parse_estimated_gate_arrival(val):
    if val is None or val is np.nan or str(val) == "nan":
        return None
    estimated_gate_arrival = get_estimated_gate_arrival_string(val)
    if estimated_gate_arrival is not None:
        datetime_obj = dateutil.parser.parse(estimated_gate_arrival)
        datetime_obj = datetime_obj.replace(tzinfo=timezone('US/Pacific'))
        datetime_obj = datetime_obj.astimezone(timezone('UTC'))
        return datetime_obj
    return None

def parse_estimated_runway_arrival(val):
    if val is None or val is np.nan or str(val) == "nan":
        return None
    estimated_runway_arrival = get_estimated_runway_arrival_string(val)
    if estimated_runway_arrival is not None:
        datetime_obj = dateutil.parser.parse(estimated_runway_arrival)
        datetime_obj = datetime_obj.replace(tzinfo=timezone('US/Pacific'))
        datetime_obj = datetime_obj.astimezone(timezone('UTC'))
        return datetime_obj
    return None


def get_flight_history_events():
    events_filename = "{0}/{1}/{2}/FlightHistory/flighthistoryevents.csv".format(data_prefix, data_rev_prefix, date_prefix)
    events_df = pd.read_csv(events_filename, na_values=na_values, parse_dates=[1], date_parser=parse_date_time)
    events_df["estimated_gate_arrival"] = events_df['data_updated'].apply(lambda x: parse_estimated_gate_arrival(x)) 
    events_df["estimated_runway_arrival"] = events_df['data_updated'].apply(lambda x: parse_estimated_runway_arrival(x)) 
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

def get_asdi_root(): 
    asdi_root_filename = "{0}/{1}/{2}/ASDI/asdiflightplan.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_root_df = pd.read_csv(asdi_root_filename, na_values=na_values, index_col=['asdiflightplanid'], parse_dates=[1,7,8,9,10], date_parser=parse_date_time)
    asdi_root_df['estimateddepartureutc_diff'] = asdi_root_df['estimateddepartureutc'] - asdi_root_df['originaldepartureutc'] 
    asdi_root_df['estimateddepartureutc_diff'] =  asdi_root_df['estimateddepartureutc_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
    asdi_root_df['estimatedarrivalutc_diff'] = asdi_root_df['estimatedarrivalutc'] - asdi_root_df['originalarrivalutc'] 
    asdi_root_df['estimatedarrivalutc_diff'] =  asdi_root_df['estimatedarrivalutc_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
    return asdi_root_df

def get_asdi_airway():
    asdi_airway_filename = "{0}/{1}/{2}/ASDI/asdiairway.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_airway_df = pd.read_csv(asdi_airway_filename, index_col=['asdiflightplanid','ordinal'], na_values=na_values)
    return asdi_airway_df

def get_asdi_fpcenter():
    asdi_asdifpcenter_filename = "{0}/{1}/{2}/ASDI/asdifpcenter.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpcenter_df = pd.read_csv(asdi_asdifpcenter_filename, index_col=['asdiflightplanid','ordinal'], na_values=na_values)
    return asdi_asdifpcenter_df

def get_asdi_pfix():
    asdi_asdifpfix_filename = "{0}/{1}/{2}/ASDI/asdifpfix.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpfix_df = pd.read_csv(asdi_asdifpfix_filename, index_col=['asdiflightplanid','ordinal'], na_values=na_values)
    return asdi_asdifpfix_df

def get_asdi_psector():
    asdi_asdifpsector_filename = "{0}/{1}/{2}/ASDI/asdifpsector.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpsector_df = pd.read_csv(asdi_asdifpsector_filename, index_col=['asdiflightplanid','ordinal'], na_values=na_values)
    return asdi_asdifpsector_df

def get_asdi_waypoint():
    asdi_asdifpwaypoint_filename = "{0}/{1}/{2}/ASDI/asdifpwaypoint.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdifpwaypoint_df = pd.read_csv(asdi_asdifpwaypoint_filename, index_col=['asdiflightplanid','ordinal'], na_values=na_values)
    return asdi_asdifpwaypoint_df

def get_asdi_disposition():
    asdi_asdiposition_filename = "{0}/{1}/{2}/ASDI/asdiposition.csv".format(data_prefix, data_rev_prefix, date_prefix)
    asdi_asdiposition_df = pd.read_csv(asdi_asdiposition_filename, parse_dates=[0], date_parser=parse_date_time, na_values=na_values)
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

def get_asdi_merged():
    asdi_root_df = get_asdi_root()
    asdi_airway_df = get_asdi_airway()
    asdi_asdifpcenter_df = get_asdi_fpcenter()
    asdi_asdifpfix_df = get_asdi_pfix()
    asdi_asdifpsector_df = get_asdi_psector()
    asdi_asdifpwaypoint_df = get_asdi_waypoint()
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

def get_atscc_deicing():
    atsccdeicing_filename = "{0}/{1}/{2}/atscc/flightstats_atsccdeicing.csv".format(data_prefix, data_rev_prefix, date_prefix)
    atsccdeicing_df = pd.read_csv(atsccdeicing_filename, index_col=[0], na_values=na_values, parse_dates=[1,2,3,4], date_parser=parse_date_time)
    end_time = []
    for ix,row in atsccdeicing_df.iterrows():
        end = row['end_time']
        if (end is None or end is np.nan ) or (row['invalidated_time'] is not None and row['invalidated_time'] is not np.nan and row['invalidated_time'] < end):
            end = row['invalidated_time']
        end_time.append(end)
    atsccdeicing_df['actual_end_time'] = pd.Series(end_time, index=atsccdeicing_df.index)
    return atsccdeicing_df

def get_atscc_delay():
    atsccdelay_filename = "{0}/{1}/{2}/atscc/flightstats_atsccdelay.csv".format(data_prefix, data_rev_prefix, date_prefix)
    atsccdelay_df = pd.read_csv(atsccdelay_filename, index_col=[0], na_values=na_values, parse_dates=[1,2,3,4], date_parser=parse_date_time)
    end_time = []
    for ix,row in atsccdelay_df.iterrows():
        end = row['end_time']
        if (end is None or end is np.nan) or (row['invalidated_time'] is not None and row['invalidated_time'] is not np.nan and row['invalidated_time'] < end):
            end = row['invalidated_time']
        end_time.append(end)
    atsccdelay_df['actual_end_time'] = pd.Series(end_time, index=atsccdelay_df.index)
    return atsccdelay_df

def get_atscc_ground_delay():
    atsccgrounddelay_filename = "{0}/{1}/{2}/atscc/flightstats_atsccgrounddelay.csv".format(data_prefix, data_rev_prefix, date_prefix)
    atsccgrounddelay_df = pd.read_csv(atsccgrounddelay_filename, index_col=[0], na_values=na_values, parse_dates=[1,2,3,4,5,8,9,10,11], date_parser=parse_date_time)
    atsccgrounddelayairports_filename = "{0}/{1}/{2}/atscc/flightstats_atsccgrounddelayairports.csv".format(data_prefix, data_rev_prefix, date_prefix)
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
    atsccgrounddelayairports_tmp_df = pd.DataFrame(groups)
    atsccgrounddelayairports_tmp_df.set_index('ground_delay_program_id', inplace=True, verify_integrity=True)
    atsccgrounddelay_merged_df = pd.merge(atsccgrounddelay_df, atsccgrounddelayairports_tmp_df, how="left", left_index=True, right_index=True)
    atsccgrounddelayartccs_filename = "{0}/{1}/{2}/atscc/flightstats_atsccgrounddelayartccs.csv".format(data_prefix, data_rev_prefix, date_prefix)
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

def get_for_flights(df):
    atsccgrounddelay_merged_df = get_atscc_ground_delay()
    atsccdelay_df = get_atscc_delay()
    atsccdeicing_df = get_atscc_deicing()
    arrival_ground_delays = []
    departure_ground_delays = []
    arrival_delays = []
    departure_delays = []
    arrival_icing_delays = []
    departure_icing_delays = []
    for ix, row in df.iterrows():
        arrival_grounddelay = {}
        departure_grounddelay = {}
        arrival_delay = {}
        departure_delay = {}
        arrival_icing_delay = {}
        departure_icing_delay = {}
        
        # if our scheduled gate arrival is within a ground delay
        if row['scheduled_gate_arrival'] is not None and row['scheduled_gate_arrival'] is not np.nan:
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
    arrival_ground_delays_df = pd.DataFrame(arrival_ground_delays)
    arrival_ground_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    arrival_delays_df = pd.DataFrame(arrival_delays)
    arrival_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    arrival_icing_delays_df = pd.DataFrame(arrival_icing_delays)
    arrival_icing_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    departure_ground_delays_df = pd.DataFrame(departure_ground_delays)
    departure_ground_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    departure_delays_df = pd.DataFrame(departure_delays)
    departure_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    departure_icing_delays_df = pd.DataFrame(departure_icing_delays)
    departure_icing_delays_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
    return (arrival_ground_delays_df, arrival_delays_df, arrival_icing_delays_df, departure_ground_delays_df, departure_delays_df, departure_icing_delays_df)


def get_joined_data(subdirname, force=False):
    date_prefix = subdirname
    print "joined_{0}".format(subdirname) in store
    if "joined_{0}".format(subdirname) in store: #os.path.isfile("{0}_joined.csv".format(subdirname)) and not force:
        try:
            df = read_dataframe("joined_{0}".format(subdirname))
            return df
        except Exception as e:
            print e
    else:
        print "Working on {0}".format(subdirname)
        df = get_flight_history()
        events = get_flight_history_events()
        # forget ASDI positioning for now, don't think we have enough information to make positions useful
        asdi_disposition = get_asdi_disposition()
        asdi_merged = get_asdi_merged() 
        joiners = [events, asdi_disposition, asdi_merged]
        df = df.join(joiners)
        per_flights = get_for_flights(df)
#        for per_flight in per_flights:
#            df = df.join(per_flight)
        joiners = per_flights
        df = df.join(joiners)
        metar_arrival = get_metar("arrival")
        metar_departure = get_metar("departure")
        df = pd.merge(df, metar_arrival, how="left", left_on="arrival_airport_icao_code", right_index=True)
        df = pd.merge(df, metar_departure, how="left", left_on="departure_airport_icao_code", right_index=True)
#        fbwind_arrival = get_fbwind("arrival")
#        fbwind_departure = get_fbwind("departure")
#        df = pd.merge(df, fbwind_arrival, how="left", left_on="arrival_airport_code", right_index=True)
#        df = pd.merge(df, fbwind_departure, how="left", left_on="departure_airport_code", right_index=True)
#        taf_arrival = get_taf("arrival")
#        df = pd.merge(df, taf_arrival, how="left", left_on="arrival_airport_code", right_index=True)
#        taf_departure = get_taf("departure")
#        df = pd.merge(df, taf_departure, how="left", left_on="departure_airport_code", right_index=True)
        print "column type counts: {0}".format(df.get_dtype_counts())
        write_dataframe("joined_{0}".format(subdirname), df)
        df = read_dataframe("joined_{0}".format(subdirname))
        print df
        return df

def get_joined_data_proxy(args):
    subdirname = args[0]
    return get_joined_data(subdirname)

def handle_datetime(x, initial):
    pass

def minutes_difference(datetime1, datetime2):
    diff = datetime1 - datetime2
    return diff.days*24*60+diff.seconds/60

def process_into_features(df, unique_cols):
    df['gate_arrival_diff'] = df['actual_gate_arrival'] - df['scheduled_gate_arrival']
    df['gate_arrival_diff'] =  df['gate_arrival_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
    df['runway_arrival_diff'] = df['actual_runway_arrival'] - df['scheduled_runway_arrival']
    df['runway_arrival_diff'] =  df['runway_arrival_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
    df['gate_departure_diff'] = df['actual_gate_departure'] - df['scheduled_gate_departure']
    df['gate_departure_diff'] = df['gate_departure_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
    df['runway_departure_diff'] = df['actual_runway_departure'] - df['scheduled_runway_departure']
    df['runway_departure_diff'] = df['runway_departure_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
    bag_o_words = {}
    bag_o_words_columns_to_delete = []
    for column, series in df.iteritems():
        try:
            # no data, no need to keep it
            #create diff columns for estimates
            if "estimated_gate_arrival" in column:
                df["{0}_diff".format(column)] = df[column] - df['scheduled_gate_arrival']
                df["{0}_diff".format(column)] = df["{0}_diff".format(column)].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
            if 'estimated_runway_arrival' in column:
                df["{0}_diff".format(column)] = df[column] - df['scheduled_runway_arrival']
                df["{0}_diff".format(column)] = df["{0}_diff".format(column)].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
            if "id" in column:
                print "id column: {0}".format(column)
    #            del df[column]
            # I hate this, but I need to figure out the type and pandas has them as all objects
            dtype_tmp = get_column_type(series)
            if dtype_tmp is datetime.datetime:
                print "datetime column: ", column
                # can't use this as this is our target
                if column == "actual_gate_arrival":
                    del df[column]
                    continue
                df['{0}_weekday'.format(column)] = df[column].apply(lambda x: x.weekday() if type(x) is datetime.datetime else np.nan)
                df['{0}_day'.format(column)] = df[column].apply(lambda x: x.day if type(x) is datetime.datetime else np.nan)
                df['{0}_hour'.format(column)] = df[column].apply(lambda x: x.hour if type(x) is datetime.datetime else np.nan)
                df['{0}_minute'.format(column)] = df[column].apply(lambda x: x.minute if type(x) is datetime.datetime else np.nan)
                # get the diff relative to a zero-point
                df['{0}_diff'.format(column)] = df['scheduled_runway_departure'] - series
                # set the diff to be in minutes
                df['{0}_diff'.format(column)] = df['{0}_diff'.format(column)].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
                # delete the original 
                if column != "scheduled_runway_departure" and column != "scheduled_gate_arrival" and column != "scheduled_runway_arrival":
                    del df[column]
            elif dtype_tmp is str:
                print column
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
                df[column] = df[column].apply(lambda x: unique_cols[column].index(x) if type(x) is str and x in unique_cols[column] and type(x) is not np.nan and str(x) != "nan" else np.nan)
            elif series.dtype is object or str(series.dtype) == "object":
                print "Column {0} is not a datetime and not a string, but is an object according to pandas: all nans: {1}".format(column, len(series.dropna()) == 0)
                #del df[column]
        except Exception as e:
            print e
            import traceback
            print traceback.format_exc()
    # join all the bag_o_words columns we found
#    bag_o_words_df = pd.DataFrame(bag_o_words.values())
#    bag_o_words_df.set_index('flight_history_id', inplace=True, verify_integrity=True)
#    df = df.join(bag_o_words_df)
    # delete the original column that made the bag o words
    for delete_column in bag_o_words_columns_to_delete:
        del df[delete_column]
    if "scheduled_runway_departure" in df.columns:
        del df["scheduled_runway_departure"]
    if "scheduled_gate_arrival" in df.columns:
        del df["scheduled_gate_arrival"]
    if "scheduled_runway_arrival" in df.columns:
        del df["scheduled_runway_arrival"]
#    df = df.convert_objects()
    for i, (column, series) in enumerate(df.iteritems()):
        if series.dtype is object or str(series.dtype) == "object":
            print "AFter convert types {0} is still an object".format(column)
            print series
            del df[column]
            #df[column] = df[column].astype(float)
    return df

def get_unique_values_for_categorical_columns(df, unique_cols):
    try:
        unique_columns = pickle.load(open("unique_columns.p",'rb'))
        return unique_columns
    except Exception as e:
        for i, (column, series) in enumerate(df.iteritems()):
            dtype_tmp = get_column_type(series)
            if series.dtype == "object" and dtype_tmp is str:
                grouped = df.groupby(column)
                for val, group in grouped:
                    if column not in unique_cols:
                        print "adding "+column, dtype_tmp, series.dtype
                        # add it to the unique cols map
                        unique_cols[column] = [] # if we have not seen this val before
                    if val not in unique_cols[column]: # append to the unqiue_cols for this column
                        unique_cols[column].append(val) # index is what we want to record for svm (svm uses floats not categorical data (strings))
            else:
                print "not uniquing {0} {1} {2}".format(column, dtype_tmp, series.dtype)
        return unique_cols

def random_forest_classify(targets, features):
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
        print cfr.feature_importances_
        features_list = []
        for j, importance in enumerate(cfr.feature_importances_):
            if importance > 0.0:
                column = features.columns[j]
                features_list.append((column, importance))
        features_list = sorted(features_list, key=lambda x: x[1], reverse=True)
        print "Features importance"
        for j, tup in enumerate(features_list):
            print j, tup
        results.append(score)

    #print out the mean of the cross-validated results
    print "Results: " + str( np.array(results).mean() )

def concat(sample_size=None):
    all_dfs = None
    for subdirname in os.walk('{0}{1}'.format(data_prefix, data_rev_prefix)).next()[1]:
        print "Working on {0}".format(subdirname)
        df = get_joined_data(subdirname)
        print "df.index",df.index
        df['gate_arrival_diff'] = df['actual_gate_arrival'] - df['scheduled_gate_arrival']
        df['gate_arrival_diff'] =  df['gate_arrival_diff'].apply(lambda x: x.days*24*60+x.seconds/60 if type(x) is datetime.timedelta else np.nan)
        # we have to have gate_arrival_diff b/c it is the target so reduce set to
        # non-nan values
        df_tmp = df.ix[df['gate_arrival_diff'].dropna().index]
        print "df_tmp.index",df_tmp.index
        samples = len(df_tmp.index) / 2
        if samples is not None:
            samples = sample_size
        rows = random.sample(df_tmp.index, samples)
        df_tmp = df_tmp.ix[rows]
        if all_dfs is None:
            all_dfs = df_tmp
            print "all_dfs after",all_dfs.index
        else:
            all_dfs = all_dfs.append(df_tmp)
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

if __name__ == '__main__':
    kind = sys.argv[1]
    if kind == "build_multi":
        pool_queue = []
        pool = Pool(processes=4)
        for subdirname in os.walk('{0}{1}'.format(data_prefix, data_rev_prefix)).next()[1]:
            pool_queue.append([subdirname])
        results = pool.map(get_joined_data_proxy, pool_queue, 1)
        pool.terminate()
    elif kind == "build":
        for subdirname in os.walk('{0}{1}'.format(data_prefix, data_rev_prefix)).next()[1]:
            get_joined_data(subdirname)
    elif kind == "concat":
        sample_size = None
        if len(sys.argv) > 2:
            sample_size = int(sys.argv[2])
        all_dfs = concat(sample_size=sample_size)
        write_dataframe("all_joined", all_dfs)
    elif kind == "generate_features":
        unique_cols = {}
        all_df = read_dataframe("all_joined")
        unique_cols = get_unique_values_for_categorical_columns(all_df, unique_cols)
        process_into_features(all_df, unique_cols)
        write_dataframe("features", all_df)
    elif kind == "uniques":
        for subdirname in os.walk('{0}{1}'.format(data_prefix, data_rev_prefix)).next()[1]:
            print "Working on {0}".format(subdirname)
            df = get_joined_data(subdirname, True)
            unique_cols = {}
            unique_cols = get_unique_values_for_categorical_columns(df, unique_cols)
            pickle.dump(unique_cols, open("unique_columns.p", "wb"))
    elif kind == "learn":
        if "features" in store:
            print "reading features from store"
            all_df = read_dataframe("features")
            for i, (column, series) in enumerate(all_df.iteritems()):
                if series.dtype is object or str(series.dtype) == "object":
                    print "AFter convert types {0} is still an object".format(column)
                    if len(series.dropna()) > 0:
                        print "is all nan and not 0:  {0}".format(len(series.dropna()))
                    del all_df[column]
        else:
            unique_cols = {}
            sample_size = None
            if len(sys.argv) > 2:
                sample_size = int(sys.argv[2])
            all_df = concat(sample_size=sample_size)
            unique_cols = get_unique_values_for_categorical_columns(all_df, unique_cols)
            all_df = process_into_features(all_df, unique_cols)
            print "writing features to features.csv"
            write_dataframe("features", all_df)
        print all_df.index
        targets = all_df['gate_arrival_diff'].dropna()
        # may want to rebin here, rounding to 5 minutes
        targets = targets.apply(lambda x: myround(x, base=5))
        print targets
        features = all_df.ix[all_df['gate_arrival_diff'].dropna().index]
        # remove the target from the features
        del features['gate_arrival_diff']
        print features
        random_forest_classify(targets, features)
        


        

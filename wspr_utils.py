from spot_processing import Station
from collections import defaultdict
import urllib.request
import numpy as np
from scipy.interpolate import splev, splrep
import matplotlib.pyplot as plt
from scipy import interpolate
import datetime, time
from coords_utils import *
import random
import matplotlib.dates as mdates

def strip_data(data):
    for i, row in enumerate(data):
        for j, el in enumerate(row):
            data[i][j] = el.strip()
    return data


def running_mean(x, N):
    x = np.array(x)
    x = np.concatenate((x, x[0:N-1]), axis=0)
    cumsum = np.cumsum(np.insert(x, 0, 0)) 
    return (cumsum[N:] - cumsum[:-N]) / float(N)


def get_url(band, spot_number, reporter):
    return "http://wsprnet.org/olddb?mode=html&band=%d&limit=%d&findcall=&findreporter=%s&sort=date" % (band, spot_number, reporter)


def download_wspr_data(band, spot_number, reporter):
    link = get_url(band, spot_number, reporter)
    contents = urllib.request.urlopen(link).read()
    
    return contents


def extract_wspr_data(contents, timestamp_start, timestamp_stop):
    d_dict = defaultdict(list)
    reporter_loc_dict = {}

    for content in contents:
        for row in content.splitlines():
            row = row.decode()
            if "<tr id=\"evenrow\"><td align=left>&nbsp;" in row or "<tr id=\"oddrow\"><td align=left>&nbsp;" in row:
                row = row.replace("&nbsp", "")
                row_list = row.split(";")[1::2]
                #print (row_list)
                timestamp = row_list[0]
                callsign = row_list[1]
                frequency = float(row_list[2])
                snr = float(row_list[3])
                locator = row_list[5]
                power = float(row_list[7])
                reporter = row_list[8]
                reporter_locator = row_list[9]
                distance = float(row_list[10])
                
                if timestamp_stop >= get_unixtime(timestamp) >= timestamp_start:
                    d_dict[reporter].append((timestamp, callsign, frequency, snr, locator, power, distance))
                    reporter_loc_dict[reporter] = (reporter_locator)
                else:
                    #d_dict[reporter].append(None)
                    reporter_loc_dict[reporter] = (reporter_locator)
                
    return reporter_loc_dict, d_dict

def extract_info(d_dict):
    callsign_dict = defaultdict(int)
    coord_dict = {}
    dist_dict = {}
    for reporter in d_dict:
        dist_dict = {el[1]: el[6] for el in d_dict[reporter]}
        for el in d_dict[reporter]:
            call = el[1]
            locator = el[4]
            callsign_dict[call] += 1
            
            coord_dict[call] = loc2coords(locator)
                
    return dist_dict, coord_dict, callsign_dict


def most_spotted(callsign_dict):
    callsign_sorted_byspots = sorted(callsign_dict, key=callsign_dict.get, reverse=True)
    return callsign_sorted_byspots


def data_by_callsign(callsign_sorted_byspots, d_dict):
    data_bycallsign_dict = {}
    for call in callsign_sorted_byspots:
        data_bycallsign_dict[call] = {}
        for reporter in d_dict:
            tmp_dict = []
            for el in d_dict[reporter]:
                if call in el:
                    tmp_dict.append(el[0:1]+el[2:])
            data_bycallsign_dict[call][reporter] = tmp_dict
    return data_bycallsign_dict


def data_by_callsign_common(data_bycallsign_dict, reporter_list):
    common_ts_bycall = {}
    for call in data_bycallsign_dict.keys():
        if sum([1 for rep in data_bycallsign_dict[call]]) == 2: # check whether callsign was heard by both reporters
            timeseries_list = []
            for rep in reporter_list:
                ts_tmp = [el[0] for el in data_bycallsign_dict[call][rep]]
                #ts_tmp = sorted(ts_tmp, key=lambda k: get_unixtime(k), reverse=False)
                timeseries_list.append(ts_tmp)
            common_ts = []
            for i, ts1 in enumerate(timeseries_list[0]):
                if ts1 in timeseries_list[1]:
                    j = timeseries_list[1].index(ts1)
                    common_ts.append((i,j))
            common_ts_bycall[call] = common_ts

    return common_ts_bycall


def get_unixtime(date_string):
    date_time_obj = datetime.datetime.strptime(date_string, '%Y-%m-%d %H:%M')
    unixtime = time.mktime(date_time_obj.timetuple())
    return unixtime


def plot_avg_snr(data_bycallsign_dict, timestamp_start, timestamp_stop, reporter_list):
    ax = plt.figure(figsize=(20,10))
    
    for i, reporter in enumerate(reporter_list):
        snr_list_ = []
        for call in data_bycallsign_dict:
            timeseries = data_bycallsign_dict[call][reporter]
            timeseries = sorted(timeseries, key=lambda k: timeseries[0], reverse=True)
            unixtime_list = [get_unixtime(el[0]) for el in timeseries]
            
            snr_list = [el[2] for el in timeseries]
            datetime_list = [datetime.datetime.fromtimestamp(ts) for ts in unixtime_list]
            snr_list_.append( (unixtime_list, snr_list) )
        
        avg_snr_dict = defaultdict(list)
        for data in snr_list_:
            ts_list = data[0]
            snr_list__ = data[1]
            for ts, snr in zip(ts_list, snr_list__):
                avg_snr_dict[ts].append(snr)
        x_list = []
        y_list = []
        for ts in avg_snr_dict:
            x_list.append(ts)
            y_list.append(np.mean(avg_snr_dict[ts]))

            #plt.errorbar(datetime.datetime.fromtimestamp(ts), np.mean(avg_snr_dict[ts]),yerr=np.std(avg_snr_dict[ts]), c=["r", "k"][i])
            plt.scatter(datetime.datetime.fromtimestamp(ts), np.mean(avg_snr_dict[ts]), c=["r", "k"][i])

        (m, b) = np.polyfit(x_list, y_list, 1)
        yp = np.polyval([m, b], x_list)
        plt.plot([datetime.datetime.fromtimestamp(x) for x in x_list], yp, c=["r", "k"][i], 
            label="Linear fit of SNR trend for %s: %f dB/h"%(reporter, m*3600))
        #plt.plot([datetime.datetime.fromtimestamp(x) for x in x_list], running_mean(y_list, 10), c=["r", "k"][i], 
        #    label="SNR running AVG for %s"%(reporter), linestyle='dashed')

    plt.grid()
    plt.title("Time evolution of SNR for two antennas (AVG)")
    plt.xlabel("Time")
    plt.ylabel("SNR (dB)")
    plt.xlim(datetime.datetime.fromtimestamp(timestamp_start), datetime.datetime.fromtimestamp(timestamp_stop))
    plt.legend()




def get_snr_bycall(callsign_sorted_byspots, data_bycallsign_dict, 
  timestamp_start, timestamp_stop, antenna_rotation_time, topn=-1, plot_flag=False):
    if plot_flag:
        ax = plt.figure(figsize=(30,20))
    snr_dict = {}
    for call in callsign_sorted_byspots[:topn]:
        snr_dict[call] = {}
        for i, reporter in enumerate(data_bycallsign_dict[call]):
            timeseries = data_bycallsign_dict[call][reporter]
            timeseries = sorted(timeseries, key=lambda k: timeseries[0], reverse=True)
            unixtime_list = [get_unixtime(el[0]) for el in timeseries]
            snr_list = [el[2] for el in timeseries]
            datetime_list = [datetime.datetime.fromtimestamp(ts) for ts in unixtime_list]
            snr_dict[call][reporter] = (unixtime_list, snr_list)
            if plot_flag:
                plt.plot(datetime_list, snr_list, "-o", label=call+" "+reporter, alpha=0.6, c=["r", "k"][i])
                #text(unixtime_list[0], snr_list[0], "%s"%call)

    #legend()
    if plot_flag:
        #plt.axvline(timestamp_start, c="r")
        #plt.axvline(antenna_rotation_time, c="b")
        plt.grid()
        plt.title("Time evolution of SNR for two antennas")
        plt.xlabel("Time")
        plt.ylabel("SNR (dB)")
        plt.xlim(datetime.datetime.fromtimestamp(timestamp_start), datetime.datetime.fromtimestamp(timestamp_stop))

    return snr_dict


def get_deltasnr_bycall(callsign_sorted_byspots, data_bycallsign_dict, dist_dict,
  timestamp_start, timestamp_stop, antenna_rotation_time, reporter_list, common_ts_bycall, rx_offset, topn=-1, plot_flag=False, country=False):
    if plot_flag:
        ax = plt.figure(figsize=(26,20))
    deltasnr_bycall_dict = {}
    for call in callsign_sorted_byspots[:topn]:
        timeseries = common_ts_bycall[call]
        if len(timeseries) == 0:
            continue
        unixtime_list = [get_unixtime(data_bycallsign_dict[call][reporter_list[0]][el[0]][0]) for el in timeseries]
        snr_list_0 = [data_bycallsign_dict[call][reporter_list[0]][el[0]][2] for el in timeseries]
        snr_list_1 = [data_bycallsign_dict[call][reporter_list[1]][el[1]][2] for el in timeseries]

        unixtime_list, snr_list_0, snr_list_1 = (list(t) for t in zip(*sorted(zip(unixtime_list, snr_list_0, snr_list_1), key=lambda k: k[0], reverse=False)))
        datetime_list = [datetime.datetime.fromtimestamp(ts) for ts in unixtime_list]
        deltasnr_list = [snr_1-snr_0-rx_offset for snr_0,snr_1 in zip(snr_list_0, snr_list_1)]

        deltasnr_bycall_dict[call] = (unixtime_list, deltasnr_list)
        if plot_flag:
            cdist = dist_dict[call]
            plt.plot(datetime_list, deltasnr_list, "-o", label=call+" "+reporter_list[0], c=cdist, cmap=plt.cm.plasma)
            if not country:
                plt.text(datetime_list[0], deltasnr_list[0]+0.5*random.random(), "%s"%call)
                if len(unixtime_list)>1:
                    plt.text(datetime_list[-1], deltasnr_list[-1]+0.5*random.random(), "%s"%call)
            else:
                plt.text(datetime_list[0], deltasnr_list[0]+0.5*random.random(), Station(call).country)

    if plot_flag:
        #plt.axvline(timestamp_start, c="r")
        #plt.axvline(antenna_rotation_time, c="b")
        plt.grid()
        plt.title("Time evolution of difference in SNR between two antennas")
        plt.xlabel("Time")
        plt.ylabel("Delta SNR (dB)")
        plt.xlim(datetime.datetime.fromtimestamp(timestamp_start), datetime.datetime.fromtimestamp(timestamp_stop))
        plt.ylim(-25, 25)
        #plt.gcf().fmt_xdata = mdates.DateFormatter('%H-%M')
        #plt.gcf().autofmt_xdate()
        #legend()
    return deltasnr_bycall_dict

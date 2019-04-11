from math import radians, cos, sin, asin, sqrt, atan2, pi, degrees


def loc2coords(maiden):
    if not isinstance(maiden, str):
        raise TypeError('Maidenhead locator must be a string')

    maiden = maiden.strip().upper()

    N = len(maiden)
    if not 8 >= N >= 2 and N % 2 == 0:
        raise ValueError('Maidenhead locator requires 2-8 characters, even number of characters')

    Oa = ord('A')
    lon = -180.
    lat = -90.
# %% first pair
    lon += (ord(maiden[0])-Oa)*20
    lat += (ord(maiden[1])-Oa)*10
# %% second pair
    if N >= 4:
        lon += int(maiden[2])*2
        lat += int(maiden[3])*1
# %%
    if N >= 6:
        lon += (ord(maiden[4])-Oa) * 5./60
        lat += (ord(maiden[5])-Oa) * 2.5/60
# %%
    if N >= 8:
        lon += int(maiden[6]) * 5./600
        lat += int(maiden[7]) * 2.5/600

    return lat, lon


def coords2loc(lat, lon, precision = 3):
    A = ord('A')
    a = divmod(lon+180, 20)
    b = divmod(lat+90, 10)
    astring = chr(A+int(a[0])) + chr(A+int(b[0]))
    lon = a[1] / 2.
    lat = b[1]
    i = 1
    while i < precision:
        i += 1
        a = divmod(lon, 1)
        b = divmod(lat, 1)
        if not (i % 2):
            astring += str(int(a[0])) + str(int(b[0]))
            lon = 24 * a[1]
            lat = 24 * b[1]
        else:
            astring += chr(A+int(a[0])) + chr(A+int(b[0]))
            lon = 10 * a[1]
            lat = 10 * b[1]

    if len(astring) >= 6:
        astring = astring[:4] + astring[4:6].lower() + astring[6:]

    return astring


def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees)
    """
    # convert decimal degrees to radians 
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # Haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    r = 6371 # Radius of earth in kilometers.

    bearing = atan2(sin(lon2-lon1)*cos(lat2), cos(lat1)*sin(lat2)-sin(lat1)*cos(lat2)*cos(lon2-lon1))
    bearing = degrees(bearing)
    bearing = (bearing + 360) % 360
    
    return c * r, bearing

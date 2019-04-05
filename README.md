# APET: Antenna Pattern Extraction Tool

_A small tool to compute antenna radiation patterns with WSPR_

The idea is to use two receivers connected to two PCs (or one decent PC with two soundcards) and to collect statistics on the received stations over a few hours (it depends on the propagation...).
Data will be collected from the WSPR webpage:
http://wsprnet.org/olddb?mode=html&band=all&limit=2000&findcall=&findreporter=is0kyb&sort=date
This call will be automated in the code in the future.

Once you have two csv files, the Jupyter Notebook will process them in steps and the result will be:
- Angle / distance distribution of the spots;
- SNR difference (between the two RXs) plot;
- Approximate antenna pattern of unknown antenna if you have a omnidirectional antenna as reference;
- Whatever you come up with :)

Of course you should live in a radio quiet area to obtain decent results.
![alt text]( "Antenna pattern example")

Try not to mix long and short propagation since it comes from different vertical angles and you would end up obtaining a horizontal pattern assiciated to several vertical angles... this seems unavoidable without special hardware.

There are two pairs of example files:
- the ones ending with 2 were "recorded" in the morning
- the other two were taken at night

Be careful to initially characterize the two rx chains by feeding them the same antenna (i.e. via a hybrid splitter) and check on the WSPR website their relative SNR values on the same spots: take the average value and put the number in the code parameter "rx_offset".

## If you like this software and find it useful you can contribute by sending me a donation to keep me working on it!
https://www.paypal.me/MarcoCogoni

73,
marco / IS0KYB

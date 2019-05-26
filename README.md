# APET: Antenna Pattern Extraction Tool

_A small tool to compute antenna radiation patterns with WSPR or FT8_

A longer presentation of this project may be found at: https://docs.google.com/document/d/1xli5nsfunJtP1ATBcLF-FFQXslA9Ovz93nYWgzLMxd0/edit?usp=sharing

The idea is to use two receivers connected to two PCs (or one decent PC with two soundcards, or SDRs) and to collect statistics on the received stations over a few hours (it depends on the propagation...). Avoid very long sessions because the F2 layer changes height, so the incoming vertical angles will change, A LOT.
Data is automatically collected from the WSPR db:
http://wsprnet.org/olddb?mode=html&band=all&limit=2000&findcall=&findreporter=is0kyb&sort=date
Data for FT8 should be produced via Robert Morris AB1HL weakmon: https://github.com/mcogoni/weakmon
My forked version implements a different SNR computation allowing much more precise data.
In this case, you should have two weakmon instances running on the same PC or two different PCs. FT8 decoding is very computationally heavy, so don't use slow computers.
The advantage of FT8 is that you have so many more signals to acquire from so many different directions and people usually use quite higher power (sic!) than WSPR. So, in general, recording times may be much shorter.

The Jupyter Notebook will process the data in steps and the result will be (you can do anything you like here...):
- Angle / distance distribution of the spots;
- SNR difference (between the two RXs) plot;
- Approximate antenna pattern of unknown antenna if you have a omnidirectional antenna as reference;

Of course you should live in a radio quiet area to obtain decent results. In particular, if you have some known local noise coming from a specific direction, the antennas should be in the same spot.

![alt text](https://github.com/mcogoni/APET/blob/master/pattern.png "Antenna pattern example")

This example pattern was obtained after about 6 hours and by exploiting the known antenna symmetry, since there are very few stations active from the South (Africa).

As told above, try not to mix long and short propagation since it comes from different vertical angles and you would end up obtaining a horizontal pattern assiciated to several vertical angles... this seems unavoidable without special hardware.

Be careful to initially characterize the two rx chains by feeding them the same antenna (i.e. via a hybrid splitter) and check on the WSPR website their relative SNR values on the same spots: take the average value and put the number in the code parameter "rx_offset".

If you're unfamiliar with Jupyter Notebook, you can easily run the code on Google Colab:
https://colab.research.google.com/github/mcogoni/APET/blob/master/WSPR_Antenna_Pattern.ipynb
and run the commands in the first cell to clone the Github code in Google Drive.
To use the notebook in read/write mode, you should save it and it will belong to you.

Another use of the same data is to plot the SNR difference between the antennas over time
to directly verify how propagation evolves, which distances are open, etc
![alt text](https://github.com/mcogoni/APET/blob/master/DeltaSNR_time.png "DeltaSNR over time")

As you can see above, from 8:00 UTC to 22:00 UTC, the highest gain of the directional antenna is
over 10dB in the morning, but it degrades over time, until North Europe vanishes ~2 hours after sunset.
Then only USA remains and the difference between the antennas grows constantly especially for 9000km paths. 

73,
marco / IS0KYB

## If you like this software and find it useful you can contribute by sending me a donation to keep me working on it!
https://www.paypal.me/MarcoCogoni

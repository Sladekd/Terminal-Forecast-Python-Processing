# Terminal-Forecast-Processing
Notebooks for aviation TAF forecast downloading, processing and decoding

If you use the code in the scientific or any published work, feel free to cite: https://journals.vilniustech.lt/index.php/Aviation/article/view/21690
In this article, all the functions, motivation and purpose are described and commented, along with analysis of TAF reports in Europe 2022.

In the meantime, feel free to cite 
DOI: 10.1109/ICMT52455.2021.9502819 or DOI: 10.3390/atmos12020138

The notebook aggregation function is process_taf_to_df, which aggregates functions based on regular expressions and combines them into a single process.

!['process_taf_to_df'](https://github.com/Sladekd/Terminal-Forecast-Python-Processing/blob/main/Taf_to_df.PNG)

## Plot Wind speed

It is also possible to use notebook Plot_ws_Taf to perform simple visualization of wind speed (but you can modify it based on the Series you want to plot).

!['Visualize Ws'](https://github.com/Sladekd/Terminal-Forecast-Python-Processing/blob/main/Ws_fcst.png)

You can also visualize gusts - this function can be usefull for minimal and maximal values.

!['Visualize Ws with Gust'](https://github.com/Sladekd/Terminal-Forecast-Python-Processing/blob/main/Ws_TAF_Gust.png)

## Procedure of decoding

To get overall idea of how the TAF is decoded and BECMG groups are handeled since they posses short time periods but change forecast untill the next BECMG/FM change, following diagram can be used.

!['Process of decoding'](https://github.com/Sladekd/Terminal-Forecast-Python-Processing/blob/main/Process.PNG)

# Scientific Observation Instrumentation Form

## Summary of the Paper
- **Content Summary**: This study investigates causal relationships between solar‑wind drivers and the magnetospheric response measured by the disturbance storm time (Dst) index. Using information‑theoretic tools—mutual information, transfer entropy, and a cumulant‑based cost—the authors quantify linear and nonlinear dependencies, focusing on the coupling between solar‑wind velocity (Vsw), the solar‑wind electric field proxy VBs (Vsw × southward IMF Bz), and Dst. The analysis utilizes long‑term solar‑wind and geomagnetic datasets spanning 1974 – 2001, with detailed examinations for the year 1999, to reveal characteristic lag times (e.g., 3–12 h, 25, 50, 90 h) associated with external driving and internal magnetospheric dynamics. The results demonstrate that transfer entropy effectively isolates the directional information flow from the solar wind to the magnetosphere, confirming the solar wind as the primary driver.

## Instrumentation Details

### Disturbance storm time index (Dst) from Kyoto University World Data Center for Geomagnetism
- **General Comments**:
  - Dst is an hourly global geomagnetic index that quantifies the strength of the symmetric ring current and is widely used to characterize magnetospheric activity.
- **Supporting Quote**: “Dst (disturbance storm time index) is an hourly index that gives a measure of the strength of the symmetric ring current.”

#### Data Collection Period 1: Overall dataset (1974–2001)
- **Time Range**: 1974–2001  
  - **Supporting Quote**: “We use Dst records in the period 1974–2001 obtained from Kyoto University World Data Center for Geomagnetism (http://swdcwww.kugi.kyoto-u.ac.jp/index.html, last access: 18 January 2018).”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “Dst (disturbance storm time index) is an hourly index that gives a measure of the strength of the symmetric ring current.”
- **Physical Observable**: Hourly index measuring the strength of the symmetric ring current.  
  - **Supporting Quote**: “Dst (disturbance storm time index) is an hourly index that gives a measure of the strength of the symmetric ring current.”
- **Additional Comments**: The Dst series provides the output variable for all causal‑information analyses presented in the paper.

#### Data Collection Period 2: Year‑specific analysis (1999)
- **Time Range**: 1999  
  - **Supporting Quote**: “In Fig. 1 we plot the signiﬁcance obtained from the year 1999 as a function of time delay, τ.”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “Dst (disturbance storm time index) is an hourly index that gives a measure of the strength of the symmetric ring current.”
- **Physical Observable**: Hourly index measuring the strength of the symmetric ring current.  
  - **Supporting Quote**: “Dst (disturbance storm time index) is an hourly index that gives a measure of the strength of the symmetric ring current.”
- **Additional Comments**: The 1999 subset is used to illustrate detailed lag‑dependent signatures in the mutual‑information, transfer‑entropy, and cumulant‑based analyses.

---

### IMP‑8 spacecraft (Solar‑wind observations)
- **General Comments**:
  - IMP‑8 provides solar‑wind plasma and magnetic‑field measurements that contribute to the composite solar‑wind dataset used for Vsw and VBs calculations.
- **Supporting Quote**: “The corresponding solar wind data are obtained from IMP‑8, ACE, WIND, ISEE1, and ISEE3 observations.”

#### Data Collection Period 1: Overall dataset (1974–2001)
- **Time Range**: 1974–2001  
  - **Supporting Quote**: “We use Dst records in the period 1974–2001 obtained from Kyoto University World Data Center for Geomagnetism (http://swdcwww.kugi.kyoto-u.ac.jp/index.html, last access: 18 January 2018).”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: Solar‑wind plasma parameters (e.g., velocity, density) and magnetic‑field components used to compute Vsw and VBs.  
  - **Supporting Quote**: “We examine the relationships between solar wind velocity (Vsw) and VBs with Dst.”
- **Additional Comments**: IMP‑8 data are integrated with other missions to provide continuous coverage over the multi‑decadal interval.

#### Data Collection Period 2: Year‑specific analysis (1999)
- **Time Range**: 1999  
  - **Supporting Quote**: “In Fig. 1 we plot the signiﬁcance obtained from the year 1999 as a function of time delay, τ.”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: Solar‑wind plasma parameters and magnetic field used for Vsw and VBs in the 1999 analysis.  
  - **Supporting Quote**: “We examine the relationships between solar wind velocity (Vsw) and VBs with Dst.”
- **Additional Comments**: The 1999 interval is used to showcase the lag‑dependent nonlinear signatures.

---

### SWEPAM on board ACE
- **General Comments**:
  - The Solar Wind Electron, Proton, and Alpha Monitor (SWEPAM) provides solar‑wind plasma measurements (velocity, density) essential for constructing Vsw.
- **Supporting Quote**: “The ACE SWEPAM and MAG data and the WIND MAG data are obtained from CDAWeb (http://cdaweb.gsfc.nasa.gov/, last access: 18 January 2018).”

#### Data Collection Period 1: Overall dataset (1974–2001)
- **Time Range**: 1974–2001  
  - **Supporting Quote**: “We use Dst records in the period 1974–2001 obtained from Kyoto University World Data Center for Geomagnetism (http://swdcwww.kugi.kyoto-u.ac.jp/index.html, last access: 18 January 2018).”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: Solar‑wind velocity (Vsw).  
  - **Supporting Quote**: “We examine the relationships between solar wind velocity (Vsw) and VBs with Dst.”
- **Additional Comments**: SWEPAM data are merged with other spacecraft to maintain uniform temporal coverage.

#### Data Collection Period 2: Year‑specific analysis (1999)
- **Time Range**: 1999  
  - **Supporting Quote**: “In Fig. 1 we plot the signiﬁcance obtained from the year 1999 as a function of time delay, τ.”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: Solar‑wind velocity (Vsw) for 1999.  
  - **Supporting Quote**: “We examine the relationships between solar wind velocity (Vsw) and VBs with Dst.”
- **Additional Comments**: The 1999 Vsw time series drives the transfer‑entropy and cumulant‑based calculations shown in Figures 1 and 2.

---

### MAG on board ACE
- **General Comments**:
  - ACE’s magnetometer supplies IMF magnetic‑field measurements (including southward Bz) required to compute the solar‑wind electric‑field proxy VBs.
- **Supporting Quote**: “The ACE SWEPAM and MAG data and the WIND MAG data are obtained from CDAWeb (http://cdaweb.gsfc.nasa.gov/, last access: 18 January 2018).”

#### Data Collection Period 1: Overall dataset (1974–2001)
- **Time Range**: 1974–2001  
  - **Supporting Quote**: “We use Dst records in the period 1974–2001 obtained from Kyoto University World Data Center for Geomagnetism (http://swdcwww.kugi.kyoto-u.ac.jp/index.html, last access: 18 January 2018).”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: Southward IMF component (Bz) used in VBs = Vsw × Bz.  
  - **Supporting Quote**: “Studies have shown that the electric ﬁeld, VBs (Vsw × southward IMF Bz), has a strong effect on the ring current dynamics.”
- **Additional Comments**: ACE MAG data are combined with SWEPAM velocity data to form the VBs time series.

#### Data Collection Period 2: Year‑specific analysis (1999)
- **Time Range**: 1999  
  - **Supporting Quote**: “In Fig. 1 we plot the signiﬁcance obtained from the year 1999 as a function of time delay, τ.”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: Southward IMF Bz for 1999, entering the VBs calculation.  
  - **Supporting Quote**: “Studies have shown that the electric ﬁeld, VBs (Vsw × southward IMF Bz), has a strong effect on the ring current dynamics.”
- **Additional Comments**: Provides the magnetic‑field component for the VBs proxy in the highlighted year.

---

### MAG on board WIND
- **General Comments**:
  - WIND’s magnetometer delivers IMF magnetic‑field data complementary to ACE, contributing to the VBs time series.
- **Supporting Quote**: “The ACE SWEPAM and MAG data and the WIND MAG data are obtained from CDAWeb (http://cdaweb.gsfc.nasa.gov/, last access: 18 January 2018).”

#### Data Collection Period 1: Overall dataset (1974–2001)
- **Time Range**: 1974–2001  
  - **Supporting Quote**: “We use Dst records in the period 1974–2001 obtained from Kyoto University World Data Center for Geomagnetism (http://swdcwww.kugi.kyoto-u.ac.jp/index.html, last access: 18 January 2018).”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: IMF magnetic‑field components (including southward Bz) for VBs computation.  
  - **Supporting Quote**: “Studies have shown that the electric ﬁeld, VBs (Vsw × southward IMF Bz), has a strong effect on the ring current dynamics.”
- **Additional Comments**: WIND MAG data fill temporal gaps and improve robustness of the solar‑wind driver series.

#### Data Collection Period 2: Year‑specific analysis (1999)
- **Time Range**: 1999  
  - **Supporting Quote**: “In Fig. 1 we plot the signiﬁcance obtained from the year 1999 as a function of time delay, τ.”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: IMF Bz for 1999, used in the VBs proxy.  
  - **Supporting Quote**: “Studies have shown that the electric ﬁeld, VBs (Vsw × southward IMF Bz), has a strong effect on the ring current dynamics.”
- **Additional Comments**: Ensures the 1999 VBs time series benefits from multiple spacecraft magnetic‑field inputs.

---

### 3DP on board WIND
- **General Comments**:
  - The 3DP (Three‑Dimensional Plasma) instrument supplies high‑resolution solar‑wind plasma measurements (velocity, density, temperature) employed in constructing Vsw.
- **Supporting Quote**: “The WIND 3DP data are obtained from the 3DP team directly.”

#### Data Collection Period 1: Overall dataset (1974–2001)
- **Time Range**: 1974–2001  
  - **Supporting Quote**: “We use Dst records in the period 1974–2001 obtained from Kyoto University World Data Center for Geomagnetism (http://swdcwww.kugi.kyoto-u.ac.jp/index.html, last access: 18 January 2018).”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: Solar‑wind velocity (Vsw) derived from plasma measurements.  
  - **Supporting Quote**: “We examine the relationships between solar wind velocity (Vsw) and VBs with Dst.”
- **Additional Comments**: WIND 3DP data complement ACE SWEPAM to ensure continuous velocity coverage.

#### Data Collection Period 2: Year‑specific analysis (1999)
- **Time Range**: 1999  
  - **Supporting Quote**: “In Fig. 1 we plot the signiﬁcance obtained from the year 1999 as a function of time delay, τ.”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: Solar‑wind velocity for 1999.  
  - **Supporting Quote**: “We examine the relationships between solar wind velocity (Vsw) and VBs with Dst.”
- **Additional Comments**: Provides the Vsw component for the 1999 VBs computation used in the case‑study figures.

---

### ISEE‑1 and ISEE‑3 spacecraft (Solar‑wind observations)
- **General Comments**:
  - ISEE‑1 and ISEE‑3 contribute additional solar‑wind plasma and magnetic‑field measurements, extending the temporal coverage of the composite solar‑wind dataset.
- **Supporting Quote**: “The ISEE1 and ISEE3 data are obtained from UCLA (these datasets are also available at NASA NSSDC; http://nssdc.gsfc.nasa.gov/, last access: 18 January 2018).”

#### Data Collection Period 1: Overall dataset (1974–2001)
- **Time Range**: 1974–2001  
  - **Supporting Quote**: “We use Dst records in the period 1974–2001 obtained from Kyoto University World Data Center for Geomagnetism (http://swdcwww.kugi.kyoto-u.ac.jp/index.html, last access: 18 January 2018).”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: Solar‑wind plasma parameters (velocity, density) and magnetic‑field components for Vsw and VBs.  
  - **Supporting Quote**: “We examine the relationships between solar wind velocity (Vsw) and VBs with Dst.”
- **Additional Comments**: Data from ISEE‑1/3 fill gaps in the multi‑mission solar‑wind record.

#### Data Collection Period 2: Year‑specific analysis (1999)
- **Time Range**: 1999  
  - **Supporting Quote**: “In Fig. 1 we plot the signiﬁcance obtained from the year 1999 as a function of time delay, τ.”
- **Wavelength(s)**: N/A  
  - **Supporting Quote**: “The solar wind is propagated with the minimum variance technique (Weimer et al., 2003) to GSM (X, Y, Z) = (17, 0, 0) RE to produce 1 min files, from which hourly averaged solar wind parameters are constructed.”
- **Physical Observable**: Solar‑wind velocity and magnetic‑field data for 1999.  
  - **Supporting Quote**: “We examine the relationships between solar wind velocity (Vsw) and VBs with Dst.”
- **Additional Comments**: Enables a complete 1999 solar‑wind driver time series for the case study.

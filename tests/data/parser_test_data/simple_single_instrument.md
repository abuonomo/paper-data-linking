# Scientific Observation Instrumentation Form

## Summary of the Paper
- **Content Summary**: The paper develops and validates automated statistical techniques (PCOut outlier detection and wavelet-enhanced ICA) to detect and analyze solar transition-region explosive events using time series of long-slit spectra. The primary data source is SUMER on SOHO, with two temporal-serial slit sequences on 2000-05-18 and 2000-05-19. The study focuses on C IV 1548.2 Å and Ne VIII 770.4 Å (observed in second order at 1540.85 Å), computing radiances, line-profile moments, and wing velocities to characterize explosive events and compare quiet Sun versus active-region peripheries.

## Instrumentation Details

### SUMER on board SOHO
- **General Comments**:
  - SUMER provided time sequences of long-slit UV spectra used to detect and statistically characterize explosive events in C IV and Ne VIII. Two temporal-serial sequences (fixed slit) with 60 s exposures and 1"×300" slit were reduced with the standard SUMER pipeline and radiometric calibration to produce calibrated data cubes for analysis.
- **Supporting Quote**: "In this work we have presented a totally automated processing of homogeneous series of spectral images taken by the SUMER spectrograph on board SOHO."

#### Data Collection Period 1: First temporal-serial slit sequence (quiet Sun and AR periphery sampling)
- **Time Range**: 2000-05-18 09:45:15 UT – 2000-05-18 14:47:16 UT
  - **Supporting Quote**: "They consist of two series of 60 seconds exposures taken with the 1′′ × 300′′ slit starting on May 18th, 2000 at 09:45:15 (ﬁrst series) ... and ending at 14:47:16 (ﬁrst series)..."
- **Wavelength(s)**:
  - C IV 1548.2 Å; Ne VIII 770.4 Å (second order at 1540.85 Å)
  - **Supporting Quote**: "The analysis is carried out for two spectral lines: the C iv line at 1548.2 Å and the Ne viii line at 770.4 Å."
  - **Supporting Quote**: "The Ne viii line at 770.4 Å appears in second order at a wavelength of 1540.85 Å."
- **Physical Observable**: Temporal sequence of long-slit spectra and derived line profiles/radiances/moments for explosive event detection and characterization
  - **Supporting Quote**: "we propose a sound statistical treatment of data cubes consisting of a temporal sequence of long slit spectra of the solar atmosphere."
- **Additional Comments**:
  - Slit fixed, Temporal Serial mode; slit centered at equator, 290″ east of central meridian; spatial resolution 0.96″; spectral resolution 0.04 Å; rotation compensation disabled.
  - Observations reduced with sum_read_corr_fts.pro (flatfield, deadtime, linearity, distortion, wavelength/flux calibration); radiometry.pro used; intensities in W m−2 sr−1 Å−1.

#### Data Collection Period 2: Second temporal-serial slit sequence (quiet Sun and AR periphery sampling)
- **Time Range**: 2000-05-19 03:55:30 UT – 2000-05-19 08:57:31 UT
  - **Supporting Quote**: "They consist of two series of 60 seconds exposures taken with the 1′′ × 300′′ slit starting on May 18th, 2000 at 09:45:15 (ﬁrst series) and May 19th at 03:55:30 (second series) and ending at 14:47:16 (ﬁrst series) and 08:57:31 (second series)."
- **Wavelength(s)**:
  - C IV 1548.2 Å; Ne VIII 770.4 Å (second order at 1540.85 Å)
  - **Supporting Quote**: "The analysis is carried out for two spectral lines: the C iv line at 1548.2 Å and the Ne viii line at 770.4 Å."
  - **Supporting Quote**: "The Ne viii line at 770.4 Å appears in second order at a wavelength of 1540.85 Å."
- **Physical Observable**: Temporal sequence of long-slit spectra and derived line profiles/radiances/moments for explosive event detection and characterization
  - **Supporting Quote**: "we propose a sound statistical treatment of data cubes consisting of a temporal sequence of long slit spectra of the solar atmosphere."
- **Additional Comments**:
  - Same instrument configuration and reduction as Period 1; analyses separate quiet Sun and regions potentially affected by NOAA 8998/9004 periphery based on context within the observing field.


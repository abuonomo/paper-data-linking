// src/components/UsageExplorer.jsx
import React, { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';
import { useUsageByMission } from '../hooks/useUsageByMission';
import { useEventsData } from '../hooks/useEventsData';

export default function UsageExplorer() {
  const { data: resp, loading: usageLoading, error: usageError } = useUsageByMission();
  const { missionLaunches, solarEvents, loading: eventsLoading, error: eventsError } = useEventsData();
  const [plotData, setPlotData] = useState([]);
  const [layout, setLayout] = useState({});
  const [config, setConfig] = useState({});
  const [showLaunches, setShowLaunches] = useState(true);
  const [showEvents, setShowEvents] = useState(true);

  // Update plot data when response or event toggles change
  useEffect(() => {
    if (resp && resp.missions) {
      updatePlotData();
    }
  }, [resp, missionLaunches, solarEvents, showLaunches, showEvents]);

  // Generate plot data from response and events
  const updatePlotData = () => {
    if (!resp) return;

    const { dates, missions, data } = resp;

    // Convert dates to proper Date objects
    const dateObjects = dates.map(date => new Date(date));

    // Generate trace for each mission
    const traces = missions.map((mission, missionIndex) => ({
      name: mission,
      x: dateObjects,
      y: data.map(row => row[missionIndex]),
      type: 'scatter',
      mode: 'none',
      fill: 'tonexty',
      stackgroup: 'one', // This makes it a stacked area chart
      fillcolor: getColor(missionIndex, 0.6),
      line: {
        color: getColor(missionIndex, 1),
        width: 1
      }
    }));

    setPlotData(traces);

    // Create annotations and shapes for missions and events
    const annotations = [];
    const shapes = [];

    // Add mission launch annotations if enabled
    if (showLaunches && missionLaunches.length > 0) {
      missionLaunches.forEach(launch => {
        const launchDate = new Date(launch.date);

        // Add annotation for mission launch
        annotations.push({
          x: launchDate,
          y: 0,
          xref: 'x',
          yref: 'paper',
          text: `↑ ${launch.mission.split(' ')[0]}`,
          showarrow: true,
          arrowhead: 7,
          ax: 0,
          ay: -40,
          arrowcolor: 'rgba(0, 128, 0, 0.7)',
          font: {
            color: 'rgba(0, 128, 0, 0.9)',
            size: 10
          },
          bordercolor: 'rgba(0, 128, 0, 0.7)',
          borderwidth: 1,
          bgcolor: 'rgba(255, 255, 255, 0.8)',
          hovertext: `${launch.mission} (${launch.date})<br>${launch.notes || ''}`,
          hoverlabel: { bgcolor: 'white' }
        });

        // Add vertical line for mission launch
        shapes.push({
          type: 'line',
          x0: launchDate,
          x1: launchDate,
          y0: 0,
          y1: 1,
          xref: 'x',
          yref: 'paper',
          line: {
            color: 'rgba(0, 128, 0, 0.3)',
            width: 1,
            dash: 'dash'
          }
        });
      });
    }

    // Add solar event annotations if enabled
    if (showEvents && solarEvents.length > 0) {
      solarEvents.forEach(event => {
        const eventDate = new Date(event.date);

        // Add annotation for solar event
        annotations.push({
          x: eventDate,
          y: 1,
          xref: 'x',
          yref: 'paper',
          text: `★ ${event.event.split(' ')[0]}`,
          showarrow: true,
          arrowhead: 7,
          ax: 0,
          ay: 40,
          arrowcolor: 'rgba(255, 0, 0, 0.7)',
          font: {
            color: 'rgba(255, 0, 0, 0.9)',
            size: 10
          },
          bordercolor: 'rgba(255, 0, 0, 0.7)',
          borderwidth: 1,
          bgcolor: 'rgba(255, 255, 255, 0.8)',
          hovertext: `${event.event} (${event.date})`,
          hoverlabel: { bgcolor: 'white' }
        });

        // Add vertical line for solar event
        shapes.push({
          type: 'line',
          x0: eventDate,
          x1: eventDate,
          y0: 0,
          y1: 1,
          xref: 'x',
          yref: 'paper',
          line: {
            color: 'rgba(255, 0, 0, 0.3)',
            width: 1,
            dash: 'dash'
          }
        });
      });
    }

    // Update layout with annotations and shapes
    setLayout({
      title: 'Dataset Usage Explorer',
      autosize: true,
      margin: { l: 50, r: 50, t: 70, b: 40 },
      annotations: annotations,
      shapes: shapes,
      legend: {
        orientation: 'v',
        yanchor: 'top',
        y: 1,
        xanchor: 'left',
        x: 1.02,
        bgcolor: 'rgba(255,255,255,0.8)',
        bordercolor: 'rgba(0,0,0,0.1)',
        borderwidth: 1,
        font: { size: 12 }
      },
      xaxis: {
        title: 'Date',
        rangeslider: { visible: true },
        type: 'date'
      },
      yaxis: {
        title: 'Usage Count',
        rangemode: 'tozero'
      },
      hovermode: 'closest',
      dragmode: 'zoom'
    });

    // Config
    setConfig({
      responsive: true,
      displayModeBar: true,
      modeBarButtonsToAdd: ['resetScale2d', 'toggleSpikelines'],
      modeBarButtonsToRemove: ['lasso2d'],
      toImageButtonOptions: {
        format: 'png',
        filename: 'dataset_usage_explorer',
        height: 800,
        width: 1200,
        scale: 2
      },
      displaylogo: false
    });
  };

  // Get colors for the chart
  function getColor(index, alpha = 1) {
    const colors = [
      `rgba(255, 99, 132, ${alpha})`,
      `rgba(54, 162, 235, ${alpha})`,
      `rgba(255, 206, 86, ${alpha})`,
      `rgba(75, 192, 192, ${alpha})`,
      `rgba(153, 102, 255, ${alpha})`,
      `rgba(255, 159, 64, ${alpha})`,
      `rgba(201, 203, 207, ${alpha})`,
    ];
    return colors[index % colors.length];
  }

  const loading = usageLoading || eventsLoading;
  const error = usageError || eventsError;

  if (loading) return <p>Loading data…</p>;
  if (error) return <p style={{ color: 'red' }}>Error loading data: {error.message}</p>;

  return (
    <div style={{ padding: '1rem' }}>
        <h1>Dataset Usage Explorer</h1>

        {/* Toggle controls for events */}
        <div style={{ marginBottom: '15px' }}>
          <label style={{ marginRight: '15px' }}>
            <input
              type="checkbox"
              checked={showLaunches}
              onChange={() => setShowLaunches(!showLaunches)}
              style={{ marginRight: '5px' }}
            />
            Show Mission Launches
          </label>
          <label>
            <input
              type="checkbox"
              checked={showEvents}
              onChange={() => setShowEvents(!showEvents)}
              style={{ marginRight: '5px' }}
            />
            Show Major Solar Events
          </label>
        </div>

        {/* Main chart container */}
        <div style={{
          height: 'calc(100vh - 200px)',
          minHeight: '600px',
          width: '100%',
          border: '1px solid #eee',
          borderRadius: '4px',
          padding: '8px'
        }}>
          <Plot
            data={plotData}
            layout={layout}
            config={config}
            style={{ width: '100%', height: '100%' }}
            useResizeHandler={true}
          />
        </div>

        {/* Legend and tips */}
        <div style={{ marginTop: '10px', fontSize: '0.9em', color: '#666' }}>
          <p><strong>Tip:</strong> Click on mission names in the legend to hide/show them. Double-click to isolate a specific mission. Use the range slider below the chart to zoom in on a specific time period.</p>
          <p><strong>Legend:</strong> <span style={{ color: 'green' }}>↑</span> Mission launches | <span style={{ color: 'red' }}>★</span> Major solar events</p>
        </div>
    </div>
  );
}
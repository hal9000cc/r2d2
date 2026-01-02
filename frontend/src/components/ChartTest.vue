<template>
  <div class="test-page">
    <h1>Lightweight Charts - setData Test</h1>
    <p>This test reproduces the issue with visible range shifting when calling setData with more bars.</p>
    
    <div class="controls">
      <button @click="runTest">Run Test</button>
      <button @click="clearLog">Clear Log</button>
    </div>
    
    <div ref="chartContainer" class="chart-container"></div>
    
    <div class="log-container">
      <div v-for="(entry, index) in logEntries" :key="index" 
           :class="['log-entry', entry.isAction ? 'log-action' : 'log-event']">
        [{{ entry.time }}] {{ entry.message }}
      </div>
    </div>
  </div>
</template>

<script>
import { createChart, CandlestickSeries } from 'lightweight-charts';

export default {
  name: 'ChartTest',
  
  data() {
    return {
      chart: null,
      series: null,
      logEntries: [],
      visibleRangeSubscription: null
    };
  },
  
  mounted() {
    this.log('Page loaded. Click "Run Test" to start.', true);
  },
  
  beforeUnmount() {
    if (this.visibleRangeSubscription && this.chart) {
      this.chart.timeScale().unsubscribeVisibleLogicalRangeChange(this.visibleRangeSubscription);
    }
    if (this.chart) {
      this.chart.remove();
    }
  },
  
  methods: {
    log(message, isAction = false) {
      const now = new Date();
      const time = now.toISOString().substr(11, 12);
      this.logEntries.push({ time, message, isAction });
      console.log(message);
      
      // Auto-scroll
      this.$nextTick(() => {
        const logContainer = this.$el.querySelector('.log-container');
        if (logContainer) {
          logContainer.scrollTop = logContainer.scrollHeight;
        }
      });
    },
    
    clearLog() {
      this.logEntries = [];
    },
    
    generateBars(count) {
      const bars = [];
      const startTime = Math.floor(Date.now() / 1000) - count * 900; // 15 min bars
      
      for (let i = 0; i < count; i++) {
        const time = startTime + i * 900;
        const open = 100 + Math.random() * 10;
        const close = open + (Math.random() - 0.5) * 5;
        const high = Math.max(open, close) + Math.random() * 2;
        const low = Math.min(open, close) - Math.random() * 2;
        
        bars.push({
          time: time,
          open: open,
          high: high,
          low: low,
          close: close
        });
      }
      
      return bars;
    },
    
    initChart() {
      // Clear previous chart
      if (this.chart) {
        if (this.visibleRangeSubscription) {
          this.chart.timeScale().unsubscribeVisibleLogicalRangeChange(this.visibleRangeSubscription);
        }
        this.chart.remove();
        this.chart = null;
      }
      
      const container = this.$refs.chartContainer;
      if (!container) {
        this.log('ERROR: Chart container not found!', true);
        return;
      }
      
      this.chart = createChart(container, {
        width: container.clientWidth,
        height: 500,
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
          shiftVisibleRangeOnNewBar: false, // CRITICAL: Disable auto-shift
          allowShiftVisibleRangeOnWhitespaceReplacement: false
        }
      });
      
      this.series = this.chart.addSeries(CandlestickSeries, {
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350'
      });
      
      // Subscribe to visible range changes
      this.visibleRangeSubscription = (logicalRange) => {
        if (logicalRange) {
          this.log(`📊 Visible range changed: from=${logicalRange.from.toFixed(2)}, to=${logicalRange.to.toFixed(2)}`);
        }
      };
      this.chart.timeScale().subscribeVisibleLogicalRangeChange(this.visibleRangeSubscription);
      
      this.log('Chart initialized', true);
    },
    
    async runTest() {
      this.clearLog();
      this.initChart();
      
      if (!this.chart || !this.series) {
        this.log('ERROR: Chart not initialized properly', true);
        return;
      }
      
      // Step 1: Set 500 bars
      this.log('Step 1: Setting 500 bars...', true);
      const bars500 = this.generateBars(500);
      this.series.setData(bars500);
      
      const range500 = this.chart.timeScale().getVisibleLogicalRange();
      this.log(`✅ After 500 bars: range from=${range500?.from.toFixed(2)}, to=${range500?.to.toFixed(2)}`);
      this.log(`   First bar time: ${bars500[0].time}, Last bar time: ${bars500[bars500.length - 1].time}`);
      
      // Wait 1 second
      this.log('⏳ Waiting 1 second...', true);
      await new Promise(resolve => setTimeout(resolve, 1000));

      const range1second = this.chart.timeScale().getVisibleLogicalRange();
      this.log(`✅ After 1 second: range from=${range1second?.from.toFixed(2)}, to=${range1second?.to.toFixed(2)}`);
      
      // Step 2: Add 200 more bars to the RIGHT (keeping first 500 unchanged)
      this.log('Step 2: Adding 200 more bars to the right (keeping first 500 unchanged)...', true);
      
      // Generate 200 new bars that continue after the last bar from bars500
      const lastBarTime = bars500[bars500.length - 1].time;
      const bars200 = this.generateBars(200);
      // Adjust times to continue after last bar
      const timeOffset = lastBarTime + 900 - bars200[0].time; // 900 = 15 minutes in seconds
      bars200.forEach(bar => {
        bar.time += timeOffset;
      });
      
      // Merge: first 500 (unchanged) + new 200 = 700 total
      const bars700 = [...bars500, ...bars200];
      
      this.log(`   Merged: ${bars500.length} (original) + ${bars200.length} (new) = ${bars700.length} total`);
      this.log(`   First bar time: ${bars700[0].time}, Last bar time: ${bars700[bars700.length - 1].time}`);
      
      const rangeBefore = this.chart.timeScale().getVisibleLogicalRange();
      this.log(`📍 Before setData(700): from=${rangeBefore?.from.toFixed(2)}, to=${rangeBefore?.to.toFixed(2)}`);
      
      this.series.setData(bars700);
      
      const rangeAfter = this.chart.timeScale().getVisibleLogicalRange();
      this.log(`📍 After setData(700): from=${rangeAfter?.from.toFixed(2)}, to=${rangeAfter?.to.toFixed(2)}`);
      
      // Calculate shift
      const shiftFrom = rangeAfter.from - rangeBefore.from;
      const shiftTo = rangeAfter.to - rangeBefore.to;
      
      if (Math.abs(shiftFrom) > 1 || Math.abs(shiftTo) > 1) {
        this.log(`❌ ERROR! Range shifted by ${shiftFrom.toFixed(2)} bars (expected ~0)`, true);
        this.log(`   Expected: Range should stay same (200 bars added to right)`, true);
        this.log(`   Actual shift: from +${shiftFrom.toFixed(2)}, to +${shiftTo.toFixed(2)}`, true);
      } else {
        this.log(`✅ OK! Range stayed stable (shift: ${shiftFrom.toFixed(2)})`, true);
      }
    }
  }
};
</script>

<style scoped>
.test-page {
  padding: 20px;
  font-family: Arial, sans-serif;
}

h1 {
  margin-bottom: 10px;
}

p {
  color: #666;
  margin-bottom: 20px;
}

.controls {
  margin-bottom: 20px;
}

button {
  padding: 10px 20px;
  font-size: 16px;
  margin-right: 10px;
  cursor: pointer;
  background: #2196F3;
  color: white;
  border: none;
  border-radius: 4px;
}

button:hover {
  background: #1976D2;
}

button:active {
  background: #0D47A1;
}

.chart-container {
  width: 100%;
  height: 500px;
  margin: 20px 0;
  border: 1px solid #ddd;
  border-radius: 4px;
}

.log-container {
  background: #f5f5f5;
  padding: 15px;
  margin-top: 20px;
  max-height: 400px;
  overflow-y: auto;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  border-radius: 4px;
  border: 1px solid #ddd;
}

.log-entry {
  margin: 3px 0;
  padding: 4px 8px;
  border-radius: 2px;
}

.log-event {
  background: #e3f2fd;
}

.log-action {
  background: #fff3e0;
  font-weight: bold;
}
</style>


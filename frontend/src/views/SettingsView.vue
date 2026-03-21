<template>
  <div class="settings-view">
    <div class="settings-scroll">
      <div class="settings-inner">

        <!-- Page header -->
        <div class="page-header">
          <h1 class="page-title">Settings</h1>
          <div class="header-actions">
            <button class="btn btn-secondary" @click="loadSettings" :disabled="loading || saving">
              Reset
            </button>
            <button class="btn btn-primary" @click="saveSettings" :disabled="loading || saving">
              <span v-if="saving">Saving…</span>
              <span v-else>Save</span>
            </button>
          </div>
        </div>

        <!-- Loading state -->
        <div v-if="loading" class="state-message">Loading settings…</div>

        <!-- Load error -->
        <div v-else-if="loadError" class="alert alert-error">
          {{ loadError }}
        </div>

        <!-- Save result notifications -->
        <div v-if="saveResult" class="save-result-panel">
          <div class="alert alert-success">
            ✓ Settings saved successfully.
            <span v-if="saveResult.changed_keys.length === 0"> No changes detected.</span>
            <span v-else> {{ saveResult.changed_keys.length }} parameter(s) updated.</span>
          </div>

          <!-- Automatic actions taken -->
          <div v-for="action in saveResult.actions_taken" :key="action" class="alert alert-info">
            <span class="alert-icon">⚡</span>
            <span v-if="action === 'quotes_service_restarted'">
              Quotes service restarted automatically with new settings.
            </span>
            <span v-else>{{ action }}</span>
          </div>

          <!-- Warnings requiring manual action -->
          <div
            v-for="warning in displayedWarnings"
            :key="warning.code"
            :class="['alert', warning.level === 'error' ? 'alert-error' : 'alert-warning']"
          >
            <span class="alert-icon">{{ warning.level === 'error' ? '⚠' : '⚡' }}</span>
            {{ warning.text }}
          </div>
        </div>

        <template v-if="!loading && !loadError">

          <!-- General -->
          <div class="settings-section">
            <div class="section-header">
              <span class="section-title">General</span>
            </div>
            <div class="form-grid">
              <div class="form-row">
                <label class="form-label">Environment</label>
                <select v-model="form.general.ENVIRONMENT" class="form-input form-select">
                  <option value="development">development</option>
                  <option value="production">production</option>
                </select>
              </div>
              <div class="form-row">
                <label class="form-label">Log Level</label>
                <select v-model="form.general.LOG_LEVEL" class="form-input form-select">
                  <option v-for="level in logLevels" :key="level">{{ level }}</option>
                </select>
              </div>
              <div class="form-row form-row-wide">
                <label class="form-label">Data Directory</label>
                <input v-model="form.general.DATA_DIR" type="text" class="form-input" />
              </div>
              <div class="form-row form-row-wide">
                <label class="form-label">Logs Directory</label>
                <input v-model="form.general.LOGS" type="text" class="form-input" />
              </div>
            </div>
          </div>

          <!-- Redis -->
          <div class="settings-section">
            <div class="section-header">
              <span class="section-title">Redis</span>
            </div>
            <div class="form-grid">
              <div class="form-row">
                <label class="form-label">Host</label>
                <input v-model="form.redis.REDIS_HOST" type="text" class="form-input" />
              </div>
              <div class="form-row">
                <label class="form-label">Port</label>
                <input v-model="form.redis.REDIS_PORT" type="text" class="form-input form-input-sm" />
              </div>
              <div class="form-row">
                <label class="form-label">Database index</label>
                <input v-model="form.redis.REDIS_DB" type="text" class="form-input form-input-sm" />
              </div>
              <div class="form-row">
                <label class="form-label">Password</label>
                <div class="input-with-toggle">
                  <input
                    v-model="form.redis.REDIS_PASSWORD"
                    :type="showPasswords.redis ? 'text' : 'password'"
                    class="form-input"
                    autocomplete="new-password"
                  />
                  <button class="toggle-btn" @click="toggle('redis')" type="button">
                    {{ showPasswords.redis ? '🙈' : '👁' }}
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Quotes Service -->
          <div class="settings-section">
            <div class="section-header">
              <span class="section-title">Quotes Service</span>
            </div>

            <!-- ClickHouse sub-group -->
            <div class="subsection-header">
              <span class="subsection-title">ClickHouse</span>
            </div>
            <div class="form-grid">
              <div class="form-row">
                <label class="form-label">Host</label>
                <input v-model="form.quotes.clickhouse.CLICKHOUSE_HOST" type="text" class="form-input" />
              </div>
              <div class="form-row">
                <label class="form-label">Port</label>
                <input v-model="form.quotes.clickhouse.CLICKHOUSE_PORT" type="text" class="form-input form-input-sm" />
              </div>
              <div class="form-row">
                <label class="form-label">Username</label>
                <input v-model="form.quotes.clickhouse.CLICKHOUSE_USERNAME" type="text" class="form-input" autocomplete="off" />
              </div>
              <div class="form-row">
                <label class="form-label">Database</label>
                <input v-model="form.quotes.clickhouse.CLICKHOUSE_DATABASE" type="text" class="form-input" />
              </div>
              <div class="form-row">
                <label class="form-label">Password</label>
                <div class="input-with-toggle">
                  <input
                    v-model="form.quotes.clickhouse.CLICKHOUSE_PASSWORD"
                    :type="showPasswords.clickhouse ? 'text' : 'password'"
                    class="form-input"
                    autocomplete="new-password"
                  />
                  <button class="toggle-btn" @click="toggle('clickhouse')" type="button">
                    {{ showPasswords.clickhouse ? '🙈' : '👁' }}
                  </button>
                </div>
              </div>
            </div>

            <!-- Queue and retry settings -->
            <div class="subsection-divider"></div>
            <div class="form-grid">
              <div class="form-row form-row-wide">
                <label class="form-label">Quote Request List</label>
                <input v-model="form.quotes.REDIS_QUOTE_REQUEST_LIST" type="text" class="form-input" />
              </div>
              <div class="form-row form-row-wide">
                <label class="form-label">Quote Response Prefix</label>
                <input v-model="form.quotes.REDIS_QUOTE_RESPONSE_PREFIX" type="text" class="form-input" />
              </div>
              <div class="form-row">
                <label class="form-label">Fetch Retry Attempts</label>
                <input v-model="form.quotes.QUOTES_FETCH_RETRY_ATTEMPTS" type="text" class="form-input form-input-sm" />
              </div>
              <div class="form-row">
                <label class="form-label">Fetch Retry Delay (s)</label>
                <input v-model="form.quotes.QUOTES_FETCH_RETRY_DELAY" type="text" class="form-input form-input-sm" />
              </div>
            </div>
          </div>

          <!-- Broker -->
          <div class="settings-section">
            <div class="section-header">
              <span class="section-title">Broker</span>
            </div>
            <div class="form-grid">
              <div class="form-row">
                <label class="form-label">Bar Wait Interval (s)</label>
                <input v-model="form.broker.BAR_WAIT_INTERVAL" type="text" class="form-input form-input-sm" />
              </div>
              <div class="form-row">
                <label class="form-label">Order Wait Interval (s)</label>
                <input v-model="form.broker.ORDER_WAIT_INTERVAL" type="text" class="form-input form-input-sm" />
              </div>
              <div class="form-row">
                <label class="form-label">Order Placement Timeout (s)</label>
                <input v-model="form.broker.ORDER_PLACEMENT_TIMEOUT" type="text" class="form-input form-input-sm" />
              </div>
            </div>
          </div>

          <!-- Others -->
          <div class="settings-section">
            <div class="section-header">
              <span class="section-title">Others</span>
            </div>
            <div class="form-grid">
              <div class="form-row">
                <label class="form-label">Symbols Cache TTL (s)</label>
                <input v-model="form.others.SYMBOLS_CACHE_TTL_SECONDS" type="text" class="form-input form-input-sm" />
              </div>
            </div>
          </div>

          <!-- Supervisor -->
          <div class="settings-section">
            <div class="section-header">
              <span class="section-title">Supervisor</span>
            </div>
            <div class="form-grid">
              <div class="form-row">
                <label class="form-label">Poll Interval (s)</label>
                <input v-model="form.supervisor.SUPERVISOR_POLL_INTERVAL" type="text" class="form-input form-input-sm" />
              </div>
              <div class="form-row">
                <label class="form-label">Max Restarts</label>
                <input v-model="form.supervisor.SUPERVISOR_MAX_RESTARTS" type="text" class="form-input form-input-sm" />
              </div>
              <div class="form-row">
                <label class="form-label">Crash Interval (s)</label>
                <input v-model="form.supervisor.SUPERVISOR_CRASH_INTERVAL" type="text" class="form-input form-input-sm" />
              </div>
              <div class="form-row">
                <label class="form-label">Force Kill Timeout (s)</label>
                <input v-model="form.supervisor.SUPERVISOR_FORCE_KILL_TIMEOUT" type="text" class="form-input form-input-sm" />
              </div>
            </div>
          </div>

          <!-- Exchange API Keys -->
          <div class="settings-section">
            <div class="section-header">
              <span class="section-title">Exchange API Keys</span>
              <button class="btn btn-secondary btn-sm" @click="addApiKey" type="button">
                + Add Exchange
              </button>
            </div>

            <div v-if="form.exchange_api_keys.length === 0" class="empty-keys">
              No exchange API keys configured.
            </div>

            <div v-else class="api-keys-table">
              <!-- Table header -->
              <div class="api-keys-header">
                <span class="col-source">Exchange</span>
                <span class="col-key">API Key</span>
                <span class="col-secret">API Secret</span>
                <span class="col-actions"></span>
              </div>

              <!-- Rows -->
              <div
                v-for="(entry, idx) in form.exchange_api_keys"
                :key="idx"
                class="api-keys-row"
              >
                <div class="col-source">
                  <SourceInput
                    v-model="entry.source"
                    :input-id="`exchange-source-${idx}`"
                    :show-label="false"
                    placeholder="e.g. bybit"
                  />
                </div>
                <div class="col-key">
                  <div class="input-with-toggle">
                    <input
                      v-model="entry.api_key"
                      :type="entry.showKey ? 'text' : 'password'"
                      class="form-input"
                      autocomplete="off"
                      placeholder="API Key"
                    />
                    <button class="toggle-btn" @click="entry.showKey = !entry.showKey" type="button">
                      {{ entry.showKey ? '🙈' : '👁' }}
                    </button>
                  </div>
                </div>
                <div class="col-secret">
                  <div class="input-with-toggle">
                    <input
                      v-model="entry.api_secret"
                      :type="entry.showSecret ? 'text' : 'password'"
                      class="form-input"
                      autocomplete="off"
                      placeholder="API Secret"
                    />
                    <button class="toggle-btn" @click="entry.showSecret = !entry.showSecret" type="button">
                      {{ entry.showSecret ? '🙈' : '👁' }}
                    </button>
                  </div>
                </div>
                <div class="col-actions">
                  <button class="btn-remove" @click="removeApiKey(idx)" type="button" title="Remove">✕</button>
                </div>
              </div>
            </div>
          </div>

          <!-- Exchange API URLs -->
          <div class="settings-section">
            <div class="section-header">
              <span class="section-title">Exchange API URLs</span>
              <button class="btn btn-secondary btn-sm" @click="addApiUrl" type="button">
                + Add Exchange
              </button>
            </div>

            <div v-if="form.exchange_api_urls.length === 0" class="empty-keys">
              No exchange API URLs configured.
            </div>

            <div v-else class="api-keys-table api-urls-table">
              <div class="api-keys-header">
                <span class="col-source">Exchange</span>
                <span class="col-key">Public API</span>
                <span class="col-secret">Private API</span>
                <span class="col-actions"></span>
              </div>

              <div
                v-for="(entry, idx) in form.exchange_api_urls"
                :key="`api-url-${idx}`"
                class="api-keys-row"
              >
                <div class="col-source">
                  <SourceInput
                    v-model="entry.source"
                    :input-id="`exchange-api-url-source-${idx}`"
                    :show-label="false"
                    placeholder="e.g. bybit"
                  />
                </div>
                <div class="col-key">
                  <input
                    v-model="entry.public_api"
                    type="text"
                    class="form-input"
                    autocomplete="off"
                    placeholder="Public API URL"
                  />
                </div>
                <div class="col-secret">
                  <input
                    v-model="entry.private_api"
                    type="text"
                    class="form-input"
                    autocomplete="off"
                    placeholder="Private API URL"
                  />
                </div>
                <div class="col-actions">
                  <button class="btn-remove" @click="removeApiUrl(idx)" type="button" title="Remove">✕</button>
                </div>
              </div>
            </div>
          </div>

        </template>

        <!-- Bottom save button (convenience) -->
        <div v-if="!loading && !loadError" class="bottom-bar">
          <button class="btn btn-primary" @click="saveSettings" :disabled="loading || saving">
            <span v-if="saving">Saving…</span>
            <span v-else>Save</span>
          </button>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { settingsApi } from '../services/settingsApi'
import SourceInput from '../components/SourceInput.vue'

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const loading = ref(false)
const saving = ref(false)
const loadError = ref(null)
const saveResult = ref(null)

const logLevels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

// Toggle visibility for password fields per section
const showPasswords = reactive({ clickhouse: false, redis: false })

// Main form data (mirrors API response shape)
const form = reactive({
  general: {
    ENVIRONMENT: 'development',
    DATA_DIR: '',
    LOGS: '',
    LOG_LEVEL: 'INFO',
  },
  redis: {
    REDIS_HOST: 'localhost',
    REDIS_PORT: '6379',
    REDIS_DB: '0',
    REDIS_PASSWORD: '',
  },
  quotes: {
    clickhouse: {
      CLICKHOUSE_HOST: 'localhost',
      CLICKHOUSE_PORT: '8123',
      CLICKHOUSE_USERNAME: 'default',
      CLICKHOUSE_PASSWORD: '',
      CLICKHOUSE_DATABASE: 'quotes',
    },
    REDIS_QUOTE_REQUEST_LIST: 'quotes:requests',
    REDIS_QUOTE_RESPONSE_PREFIX: 'quotes:responses',
    QUOTES_FETCH_RETRY_ATTEMPTS: '3',
    QUOTES_FETCH_RETRY_DELAY: '1',
  },
  broker: {
    BAR_WAIT_INTERVAL: '60.0',
    ORDER_WAIT_INTERVAL: '1.0',
    ORDER_PLACEMENT_TIMEOUT: '60.0',
  },
  others: {
    SYMBOLS_CACHE_TTL_SECONDS: '600',
  },
  supervisor: {
    SUPERVISOR_POLL_INTERVAL: '3.0',
    SUPERVISOR_MAX_RESTARTS: '3',
    SUPERVISOR_CRASH_INTERVAL: '60.0',
    SUPERVISOR_FORCE_KILL_TIMEOUT: '300.0',
  },
  exchange_api_keys: [],
  exchange_api_urls: [],
})

// ---------------------------------------------------------------------------
// Warning display mapping
// ---------------------------------------------------------------------------

const WARNING_MAP = {
  restart_required: {
    level: 'error',
    text: 'Full application restart required — Redis connection or environment settings changed. New values will take effect after restart.',
  },
  restart_trading_tasks: {
    level: 'warning',
    text: 'Restart active trading tasks — broker timing or API key changes take effect when tasks are next started.',
  },
  restart_supervisor: {
    level: 'warning',
    text: 'Restart supervisor — supervisor timing settings take effect only after the supervisor process is restarted.',
  },
}

const displayedWarnings = computed(() => {
  if (!saveResult.value) return []
  return saveResult.value.warnings
    .filter(w => !w.startsWith('quotes_service_restart_failed'))
    .map(w => {
      if (WARNING_MAP[w]) return { code: w, ...WARNING_MAP[w] }
      if (w.startsWith('quotes_service_restart_failed:')) {
        return {
          code: w,
          level: 'error',
          text: `Quotes service restart failed: ${w.replace('quotes_service_restart_failed:', '')}`,
        }
      }
      return { code: w, level: 'warning', text: w }
    })
})

// ---------------------------------------------------------------------------
// Password visibility toggle
// ---------------------------------------------------------------------------

function toggle(field) {
  showPasswords[field] = !showPasswords[field]
}

// ---------------------------------------------------------------------------
// Exchange API keys
// ---------------------------------------------------------------------------

function addApiKey() {
  form.exchange_api_keys.push({ source: '', api_key: '', api_secret: '', showKey: false, showSecret: false })
}

function removeApiKey(idx) {
  form.exchange_api_keys.splice(idx, 1)
}

function addApiUrl() {
  form.exchange_api_urls.push({ source: '', public_api: '', private_api: '' })
}

function removeApiUrl(idx) {
  form.exchange_api_urls.splice(idx, 1)
}

// ---------------------------------------------------------------------------
// Load / save
// ---------------------------------------------------------------------------

function applyData(data) {
  Object.assign(form.general, data.general || {})
  Object.assign(form.redis, data.redis || {})
  Object.assign(form.broker, data.broker || {})
  Object.assign(form.others, data.others || {})
  Object.assign(form.supervisor, data.supervisor || {})

  if (data.quotes) {
    if (data.quotes.clickhouse) {
      Object.assign(form.quotes.clickhouse, data.quotes.clickhouse)
    }
    const { clickhouse, ...quotesRest } = data.quotes
    Object.assign(form.quotes, quotesRest)
  }

  form.exchange_api_keys = (data.exchange_api_keys || []).map(e => ({
    source: e.source || '',
    api_key: e.api_key || '',
    api_secret: e.api_secret || '',
    showKey: false,
    showSecret: false,
  }))

  form.exchange_api_urls = (data.exchange_api_urls || []).map(e => ({
    source: e.source || '',
    public_api: e.public_api || '',
    private_api: e.private_api || '',
  }))
}

async function loadSettings() {
  loading.value = true
  loadError.value = null
  saveResult.value = null
  try {
    const data = await settingsApi.getSettings()
    applyData(data)
  } catch (err) {
    const detail = err.response?.data?.detail || err.message
    loadError.value = `Failed to load settings: ${detail}`
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  saving.value = true
  saveResult.value = null
  try {
    // Strip UI-only fields before sending
    const payload = {
      general: { ...form.general },
      redis: { ...form.redis },
      quotes: {
        clickhouse: { ...form.quotes.clickhouse },
        REDIS_QUOTE_REQUEST_LIST: form.quotes.REDIS_QUOTE_REQUEST_LIST,
        REDIS_QUOTE_RESPONSE_PREFIX: form.quotes.REDIS_QUOTE_RESPONSE_PREFIX,
        QUOTES_FETCH_RETRY_ATTEMPTS: form.quotes.QUOTES_FETCH_RETRY_ATTEMPTS,
        QUOTES_FETCH_RETRY_DELAY: form.quotes.QUOTES_FETCH_RETRY_DELAY,
      },
      broker: { ...form.broker },
      others: { ...form.others },
      supervisor: { ...form.supervisor },
      exchange_api_keys: form.exchange_api_keys.map(({ source, api_key, api_secret }) => ({
        source,
        api_key,
        api_secret,
      })),
      exchange_api_urls: form.exchange_api_urls
        .map(({ source, public_api, private_api }) => ({
          source,
          public_api,
          private_api,
        }))
        .filter(entry => entry.public_api || entry.private_api),
    }
    const result = await settingsApi.saveSettings(payload)
    saveResult.value = result
    // Scroll to top so user sees the result
    document.querySelector('.settings-scroll')?.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (err) {
    const detail = err.response?.data?.detail || err.message
    saveResult.value = {
      success: false,
      changed_keys: [],
      actions_taken: [],
      warnings: [],
      error: detail,
    }
  } finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<style scoped>
.settings-view {
  width: 100%;
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.settings-scroll {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-xl);
}

.settings-inner {
  max-width: 900px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xl);
  padding-bottom: var(--spacing-3xl);
}

/* Page header */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-lg);
}

.page-title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
  margin: 0;
}

.header-actions {
  display: flex;
  gap: var(--spacing-sm);
}

/* State messages */
.state-message {
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
  text-align: center;
  padding: var(--spacing-2xl);
}

/* Alert boxes */
.alert {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-sm);
  padding: var(--spacing-md) var(--spacing-lg);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
}

.alert-icon {
  flex-shrink: 0;
  font-size: var(--font-size-base);
}

.alert-success {
  background-color: var(--color-success-light);
  color: var(--color-success);
  border: 1px solid var(--color-success-lighter);
}

.alert-info {
  background-color: var(--color-info-light);
  color: var(--color-info);
  border: 1px solid var(--color-info-lighter);
}

.alert-warning {
  background-color: var(--color-warning-light);
  color: var(--color-warning);
  border: 1px solid #ffe0b2;
}

.alert-error {
  background-color: var(--color-danger-light);
  color: var(--color-danger);
  border: 1px solid var(--color-danger-lighter);
}

.save-result-panel {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

/* Settings sections */
.settings-section {
  background-color: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-md) var(--spacing-lg);
  background-color: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
}

.section-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* Subsection within a section */
.subsection-header {
  padding: var(--spacing-sm) var(--spacing-lg);
  background-color: var(--bg-tertiary, var(--bg-secondary));
  border-bottom: 1px solid var(--border-color);
}

.subsection-title {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.subsection-divider {
  height: 1px;
  background-color: var(--border-color);
  margin: 0 var(--spacing-lg);
}

/* Form grid */
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  padding: var(--spacing-md);
  gap: var(--spacing-sm) var(--spacing-lg);
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.form-row-wide {
  grid-column: 1 / -1;
}

.form-label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--text-tertiary);
  user-select: none;
}

.form-input {
  height: var(--button-height-md);
  padding: 0 var(--spacing-sm);
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  background-color: var(--bg-primary);
  border: 1px solid var(--border-color-dark);
  border-radius: var(--radius-sm);
  transition: border-color var(--transition-base), box-shadow var(--transition-base);
  width: 100%;
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.form-select {
  cursor: pointer;
  appearance: auto;
}

.form-input-sm {
  max-width: 160px;
}

/* Password field with toggle */
.input-with-toggle {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.input-with-toggle .form-input {
  flex: 1;
  min-width: 0;
}

.toggle-btn {
  flex-shrink: 0;
  width: 32px;
  height: var(--button-height-md);
  border: 1px solid var(--border-color-dark);
  border-radius: var(--radius-sm);
  background-color: var(--bg-secondary);
  cursor: pointer;
  font-size: var(--font-size-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background-color var(--transition-base);
  padding: 0;
  line-height: 1;
}

.toggle-btn:hover {
  background-color: var(--bg-hover);
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: var(--button-height-md);
  padding: 0 var(--spacing-lg);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all var(--transition-base);
  white-space: nowrap;
  user-select: none;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-primary {
  background-color: var(--color-primary);
  color: var(--color-white);
  border-color: var(--color-primary);
}

.btn-primary:hover:not(:disabled) {
  background-color: var(--color-primary-hover);
  border-color: var(--color-primary-hover);
}

.btn-secondary {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
  border-color: var(--border-color-dark);
}

.btn-secondary:hover:not(:disabled) {
  background-color: var(--bg-hover);
}

.btn-sm {
  height: var(--button-height-sm);
  padding: 0 var(--spacing-md);
  font-size: var(--font-size-xs);
}

/* Exchange API keys table */
.empty-keys {
  padding: var(--spacing-lg);
  font-size: var(--font-size-sm);
  color: var(--text-muted);
}

.api-keys-table {
  padding: var(--spacing-md);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.api-keys-header,
.api-keys-row {
  display: grid;
  grid-template-columns: 160px 1fr 1fr 32px;
  gap: var(--spacing-sm);
  align-items: center;
}

.api-keys-header {
  padding-bottom: var(--spacing-xs);
  border-bottom: 1px solid var(--border-color);
}

.api-keys-header span {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.api-keys-row {
  padding: var(--spacing-xs) 0;
}

/* SourceInput inside the table — reset form-group padding/gap */
.col-source :deep(.form-group) {
  gap: 0;
}

.col-source :deep(.form-input) {
  height: var(--button-height-md);
  padding: 0 var(--spacing-sm);
  border-radius: var(--radius-sm);
  min-width: unset;
}

.btn-remove {
  width: 28px;
  height: 28px;
  border: 1px solid var(--border-color-dark);
  border-radius: var(--radius-sm);
  background-color: var(--bg-secondary);
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: var(--font-size-xs);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  transition: all var(--transition-base);
}

.btn-remove:hover {
  background-color: var(--color-danger-light);
  color: var(--color-danger);
  border-color: var(--color-danger);
}

/* Bottom bar */
.bottom-bar {
  display: flex;
  justify-content: flex-end;
  padding-top: var(--spacing-md);
}
</style>

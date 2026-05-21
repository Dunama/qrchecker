import './App.css'
import { useMemo, useState } from 'react'
import { API_BASE_URL, createOrder, getTimeline, scan } from './api'

function toPrettyJson(value) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function parseJson(text) {
  const trimmed = (text || '').trim()
  if (!trimmed) throw new Error('Paste the qr_token JSON first.')
  return JSON.parse(trimmed)
}

function App() {
  // Create order
  const [itemCode, setItemCode] = useState('')
  const [deliveryWindow, setDeliveryWindow] = useState('2–4 hours')
  const [createLoading, setCreateLoading] = useState(false)
  const [createError, setCreateError] = useState('')
  const [createResult, setCreateResult] = useState(null)

  // Scan / advance
  const [scanRole, setScanRole] = useState('seller')
  const [scanNotes, setScanNotes] = useState('')
  const [scanTokenText, setScanTokenText] = useState('')
  const [scanLoading, setScanLoading] = useState(false)
  const [scanError, setScanError] = useState('')
  const [scanResult, setScanResult] = useState(null)

  // Timeline
  const [timelineOrderId, setTimelineOrderId] = useState('')
  const [timelineLoading, setTimelineLoading] = useState(false)
  const [timelineError, setTimelineError] = useState('')
  const [timelineResult, setTimelineResult] = useState(null)

  const lastKnownOrderId = useMemo(() => {
    return (
      (createResult && createResult.order_id) ||
      (scanResult && (scanResult.order_id || scanResult.oid)) ||
      ''
    )
  }, [createResult, scanResult])

  async function onCreateOrder(e) {
    e.preventDefault()
    setCreateError('')
    setCreateResult(null)
    setTimelineResult(null)

    const item_code = itemCode.trim()
    if (!item_code) {
      setCreateError('Item code is required.')
      return
    }

    setCreateLoading(true)
    try {
      const result = await createOrder({
        item_code,
        delivery_window: deliveryWindow.trim() || '2–4 hours',
      })

      setCreateResult(result)

      if (result?.qr_token) {
        setScanTokenText(toPrettyJson(result.qr_token))
      }
      if (result?.order_id) {
        setTimelineOrderId(result.order_id)
      }
    } catch (err) {
      setCreateError(err.message || 'Failed to create order.')
    } finally {
      setCreateLoading(false)
    }
  }

  async function onScan(e) {
    e.preventDefault()
    setScanError('')
    setScanResult(null)

    let token
    try {
      token = parseJson(scanTokenText)
    } catch (err) {
      setScanError(`Invalid JSON: ${err.message}`)
      return
    }

    setScanLoading(true)
    try {
      const result = await scan({
        qr_token: token,
        role: scanRole,
        notes: scanNotes.trim() || null,
      })
      setScanResult(result)

      const oid = result?.order_id
      if (oid) setTimelineOrderId(oid)
    } catch (err) {
      setScanError(err.message || 'Scan failed.')
    } finally {
      setScanLoading(false)
    }
  }

  async function onFetchTimeline(e) {
    e.preventDefault()
    setTimelineError('')
    setTimelineResult(null)

    const id = timelineOrderId.trim()
    if (!id) {
      setTimelineError('Order ID is required.')
      return
    }

    setTimelineLoading(true)
    try {
      const result = await getTimeline(id)
      setTimelineResult(result)
    } catch (err) {
      setTimelineError(err.message || 'Failed to fetch timeline.')
    } finally {
      setTimelineLoading(false)
    }
  }

  return (
    <div className="container">
      <header className="header">
        <h1>Rental QR Tracker</h1>
      </header>

      <section className="card">
        <h2>Create Order</h2>
        <form className="grid" onSubmit={onCreateOrder}>
          <label>
            Item code
            <input
              value={itemCode}
              onChange={(e) => setItemCode(e.target.value)}
              placeholder="e.g. DRESS-001"
              autoComplete="off"
            />
          </label>

          <label>
            Delivery window
            <input
              value={deliveryWindow}
              onChange={(e) => setDeliveryWindow(e.target.value)}
              placeholder="2–4 hours"
              autoComplete="off"
            />
          </label>

          <div className="actions">
            <button type="submit" disabled={createLoading}>
              {createLoading ? 'Creating…' : 'Create + Generate QR'}
            </button>
            {createError ? <span className="error">{createError}</span> : null}
          </div>
        </form>

        {createResult ? (
          <div className="result">
            <div className="row">
              <div>
                <div className="label">order_id</div>
                <code>{createResult.order_id}</code>
              </div>
              {createResult.qr_image_b64 ? (
                <img
                  className="qr"
                  alt="QR code"
                  src={`data:image/png;base64,${createResult.qr_image_b64}`}
                />
              ) : null}
            </div>

            <label>
              qr_token (copy/paste into Scan)
              <textarea
                readOnly
                value={toPrettyJson(createResult.qr_token)}
                rows={6}
              />
            </label>
          </div>
        ) : null}
      </section>

      <section className="card">
        <h2>Scan / Advance Stage</h2>
        <form className="grid" onSubmit={onScan}>
          <label>
            Role
            <select value={scanRole} onChange={(e) => setScanRole(e.target.value)}>
              <option value="seller">seller</option>
              <option value="hotel">hotel</option>
              <option value="logistics">logistics</option>
              <option value="renter">renter</option>
            </select>
          </label>

          <label>
            Notes (optional — used by hotel)
            <input
              value={scanNotes}
              onChange={(e) => setScanNotes(e.target.value)}
              placeholder="e.g. stain on left sleeve"
              autoComplete="off"
            />
          </label>

          <label className="full">
            qr_token JSON
            <textarea
              value={scanTokenText}
              onChange={(e) => setScanTokenText(e.target.value)}
              placeholder='Paste the qr_token object here (e.g. {"oid":"...","iat":...})'
              rows={8}
            />
          </label>

          <div className="actions full">
            <button type="submit" disabled={scanLoading}>
              {scanLoading ? 'Scanning…' : 'Scan'}
            </button>
            {scanError ? <span className="error">{scanError}</span> : null}
          </div>
        </form>

        {scanResult ? (
          <div className="result">
            <div className="row">
              {'message' in scanResult ? (
                <div>
                  <div className="label">message</div>
                  <div>{scanResult.message}</div>
                </div>
              ) : null}
              {'request_id' in scanResult ? (
                <div>
                  <div className="label">request_id</div>
                  <code>{scanResult.request_id}</code>
                </div>
              ) : null}
              {'current_stage' in scanResult ? (
                <div>
                  <div className="label">current_stage</div>
                  <code>{scanResult.current_stage}</code>
                </div>
              ) : null}
              {'event' in scanResult ? (
                <div>
                  <div className="label">event</div>
                  <code>{scanResult.event}</code>
                </div>
              ) : null}
            </div>
            {scanResult.blocked ? (
              <div className="resultNote">
                <div className="label">debug</div>
                <div>
                  Expected next stage: <code>{String(scanResult.next_expected_stage)}</code>
                </div>
                {Array.isArray(scanResult.next_expected_by_roles) &&
                scanResult.next_expected_by_roles.length ? (
                  <div>
                    Next handled by:{' '}
                    <code>{scanResult.next_expected_by_roles.join(', ')}</code>
                  </div>
                ) : null}
              </div>
            ) : null}
            <label>
              Response JSON
              <textarea readOnly value={toPrettyJson(scanResult)} rows={8} />
            </label>
          </div>
        ) : null}
      </section>

      <section className="card">
        <h2>Timeline</h2>
        <form className="grid" onSubmit={onFetchTimeline}>
          <label className="full">
            Order ID
            <input
              value={timelineOrderId}
              onChange={(e) => setTimelineOrderId(e.target.value)}
              placeholder="Paste an order_id"
              autoComplete="off"
            />
          </label>
          <div className="actions full">
            <button type="submit" disabled={timelineLoading}>
              {timelineLoading ? 'Loading…' : 'Fetch Timeline'}
            </button>
            {timelineError ? <span className="error">{timelineError}</span> : null}
          </div>
        </form>

        {timelineResult?.events ? (
          <div className="result">
            <div className="label">Events</div>
            <ul className="events">
              {timelineResult.events.map((e, idx) => (
                <li key={idx}>
                  <div className="eventTop">
                    <code>{String(e.stage)}</code>
                    <span className="muted">{e.ts}</span>
                  </div>
                  <div className="muted">by: {String(e.by)}</div>
                  {e.notes ? <div className="muted">notes: {e.notes}</div> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>
    </div>
  )
}

export default App

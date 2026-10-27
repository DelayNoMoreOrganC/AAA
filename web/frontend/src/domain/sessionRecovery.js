// One refresh for concurrent 401s. Failed networking must not erase editor state.
export function createSessionRecovery({ getSession, refresh, save, expire, retry }) {
  let pending = null
  return async function recover(error) {
    const config = error.config
    if (error.response?.status !== 401 || !config || config.__sessionRetried || /\/auth\/(login|name-login|register|refresh)(?:\?|$)/.test(config.url || '')) throw error
    const session = getSession()
    if (!session.token || !session.refreshToken) throw error
    config.__sessionRetried = true
    const authorization = config.headers?.Authorization || config.headers?.authorization
    // A delayed failure may belong to the token already replaced by another call.
    if (authorization === 'Bearer ' + session.token || !authorization) {
      if (!pending) {
        const expectedRefresh = session.refreshToken
        pending = (async () => {
          try {
            const tokens = await refresh(expectedRefresh)
            if (getSession().refreshToken !== expectedRefresh) throw new Error('登录状态已改变，请重试')
            if (!tokens.access_token || !tokens.refresh_token) throw new Error('登录续期暂未完成，请重试')
            save(tokens)
          } catch (failure) {
            if ([401, 403].includes(failure.response?.status) && getSession().refreshToken === expectedRefresh) expire()
            throw failure
          }
        })().finally(() => { pending = null })
      }
      await pending
    }
    const token = getSession().token
    if (!token) throw error
    config.headers = config.headers || {}
    config.headers.Authorization = 'Bearer ' + token
    return retry(config)
  }
}

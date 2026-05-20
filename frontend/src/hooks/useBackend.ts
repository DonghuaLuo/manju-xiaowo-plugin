import { useEffect, useState, useCallback } from "react"
import { PluginSDK } from "xiaowo-sdk"

/**
 * 后端通信 Hook
 */
export function useBackend() {
  const [isReady, setIsReady] = useState(false)
  const [backendReady, setBackendReady] = useState(false)

  useEffect(() => {
    // 等待 SDK 初始化
    PluginSDK.waitReady().then(async () => {
      setIsReady(true)

      // 主动查询后端状态（防止错过就绪事件）
      try {
        const state = await PluginSDK.getBackendState()
        if (state.is_ready) {
          setBackendReady(true)
        }
      } catch (error) {
        console.error("查询后端状态失败:", error)
      }
    })

    // 监听后端就绪事件（保存 unlisten 函数）
    const unlistenReady = PluginSDK.onBackendReady(() => {
      setBackendReady(true)
    })

    return () => {
      unlistenReady?.()
    }
  }, [])

  /**
   * 调用后端方法
   */
  const callBackend = useCallback(
    async <T = any>(method: string, params: any = {}): Promise<T> => {
      if (!isReady) {
        throw new Error("SDK 未就绪")
      }
      if (!backendReady) {
        console.warn("后端尚未就绪，但仍尝试调用:", method)
      }
      return await PluginSDK.callBackend<T>(method, params)
    },
    [isReady, backendReady]
  )

  /**
   * 监听后端事件
   */
  const onBackendEvent = useCallback(
    (eventName: string, callback: (data: any) => void) => {
      PluginSDK.onBackendEvent(eventName, callback)
      return () => {
        PluginSDK.offBackendEvent(eventName)
      }
    },
    []
  )

  return {
    isReady,
    backendReady,
    callBackend,
    onBackendEvent,
  }
}

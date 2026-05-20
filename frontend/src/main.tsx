import { StrictMode, useEffect } from "react"
import { createRoot } from "react-dom/client"
import { PluginSDK } from "xiaowo-sdk"
import { Toaster } from "sonner"
import App from "./App.tsx"
import "./styles/globals.css"

function Root() {
  useEffect(() => {
    // UI 渲染完毕后显示窗口
    PluginSDK.showWindow()
  }, [])

  return (
    <StrictMode>
      <App />
      <Toaster
        position="top-center"
        toastOptions={{ style: { minWidth: "400px" } }}
      />
    </StrictMode>
  )
}

createRoot(document.getElementById("root")!).render(<Root />)

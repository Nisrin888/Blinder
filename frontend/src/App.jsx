import { ChatProvider } from './context/ChatContext';
import { Sidebar } from './components/Sidebar';
import { ChatInterface } from './components/ChatInterface';
import { SettingsPanel } from './components/SettingsPanel';

function App() {
  return (
    <ChatProvider>
      <div className="app">
        <Sidebar />
        <main className="app__main">
          <ChatInterface />
        </main>
        <SettingsPanel />
      </div>
    </ChatProvider>
  );
}

export default App;

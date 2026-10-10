import 'react-native-gesture-handler';
import { useEffect } from 'react';
import { AppState } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { Stack } from 'expo-router';
import { QueryClientProvider, focusManager } from '@tanstack/react-query';
import { StatusBar } from 'expo-status-bar';
import { queryClient } from '../lib/query';
import { SessionProvider } from '../lib/session';
export default function Layout() {
  useEffect(() => { const sub = AppState.addEventListener('change', state => focusManager.setFocused(state === 'active')); return () => sub.remove(); }, []);
  return <GestureHandlerRootView style={{ flex: 1 }}><SafeAreaProvider><QueryClientProvider client={queryClient}><SessionProvider>
    <StatusBar style="dark" /><Stack screenOptions={{ headerShown: false }} />
  </SessionProvider></QueryClientProvider></SafeAreaProvider></GestureHandlerRootView>;
}

import { useCallback } from 'react';
import axios, { AxiosInstance, AxiosError } from 'axios';
import { useAuthStore } from './useAuthStore';
import { useToast } from '@/components/ToastContainer';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'https://api.ghyiab.example.com/api';

function createApiClient(initData: string | null): AxiosInstance {
  const client = axios.create({
    baseURL: API_BASE_URL,
    timeout: 30000,
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
  });

  // Add initData to requests for Telegram Web App authentication
  client.interceptors.request.use((config) => {
    if (initData) {
      config.headers['X-Telegram-Init-Data'] = initData;
    }
    return config;
  });

  // Handle errors globally
  client.interceptors.response.use(
    (response) => response,
    (error: AxiosError) => {
      if (error.response?.status === 401) {
        useAuthStore.getState().logout();
      }
      return Promise.reject(error);
    }
  );

  return client;
}

export function useApi() {
  const { initData } = useAuthStore();
  const { error: showError } = useToast();

  const api = createApiClient(initData);

  const get = useCallback(
    async <T>(url: string, params?: object) => {
      try {
        const response = await api.get<T>(url, { params });
        return response.data;
      } catch (e) {
        if (axios.isAxiosError(e)) {
          showError(e.response?.data?.message || e.message);
        }
        throw e;
      }
    },
    [showError]
  );

  const post = useCallback(
    async <T>(url: string, data?: object) => {
      try {
        const response = await api.post<T>(url, data);
        return response.data;
      } catch (e) {
        if (axios.isAxiosError(e)) {
          showError(e.response?.data?.message || e.message);
        }
        throw e;
      }
    },
    [showError]
  );

  const put = useCallback(
    async <T>(url: string, data?: object) => {
      try {
        const response = await api.put<T>(url, data);
        return response.data;
      } catch (e) {
        if (axios.isAxiosError(e)) {
          showError(e.response?.data?.message || e.message);
        }
        throw e;
      }
    },
    [showError]
  );

  const del = useCallback(
    async <T>(url: string) => {
      try {
        const response = await api.delete<T>(url);
        return response.data;
      } catch (e) {
        if (axios.isAxiosError(e)) {
          showError(e.response?.data?.message || e.message);
        }
        throw e;
      }
    },
    [showError]
  );

  return { get, post, put, delete: del, api };
}

// Types for API responses
export interface Service {
  id: number;
  name: string;
  description: string;
  price_minor: number;
  currency: string;
  duration_days: number;
  traffic_gb: number;
  inbound_id: number;
  provider_name: string;
  is_active: boolean;
  features?: string[];
}

export interface Order {
  id: number;
  service_id: number;
  status: 'pending' | 'paid' | 'provisioning' | 'active' | 'expired' | 'cancelled';
  price_minor: number;
  currency: string;
  created_at: string;
  expires_at?: string;
  client_uuid?: string;
  subscription_url?: string;
}

export interface Wallet {
  balance_minor: number;
  currency: string;
  transactions: Transaction[];
}

export interface Transaction {
  id: number;
  amount_minor: number;
  type: 'deposit' | 'withdrawal' | 'purchase' | 'refund' | 'referral';
  description: string;
  created_at: string;
  balance_after_minor: number;
}

export interface UserProfile {
  id: number;
  username?: string;
  first_name: string;
  last_name?: string;
  phone_number?: string;
  is_agent: boolean;
  wallet_balance_minor: number;
  referral_code: string;
  referral_earnings_minor: number;
  created_at: string;
}

export interface PaymentRequest {
  gateway: string;
  amount_minor: number;
  order_id: number;
  description: string;
}

export interface PaymentResponse {
  payment_url: string;
  authority: string;
  reference_id: string;
}